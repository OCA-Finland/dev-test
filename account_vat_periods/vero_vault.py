"""Encrypted credential storage with durable, independently committed writes.

No ORM model exposes this table. Only ciphertext crosses the SQL boundary.
The caller holds a PostgreSQL session advisory lock for the entire operation,
including commits and the external PKI call. Never commit the caller's cursor.
"""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath

from cryptography.fernet import Fernet, InvalidToken

from .vero_payload import _

LOCK_NAMESPACE = 1447383631


def cipher_from_config(config, error):
    key = os.environ.get('ODOO_VERO_ENCRYPTION_KEY') or config.get('vero_encryption_key')
    key_file = os.environ.get('ODOO_VERO_ENCRYPTION_KEY_FILE') or config.get('vero_encryption_key_file')
    if not key and key_file:
        try:
            key = Path(key_file).read_text(encoding='ascii').strip()
        except (OSError, UnicodeError):
            raise error(_('The Vero storage encryption key file cannot be read. Ask your administrator to check the server configuration.')) from None
    if not key:
        raise error(_(
            'Encrypted Vero storage is not configured. Ask your administrator to set '
            'ODOO_VERO_ENCRYPTION_KEY, vero_encryption_key or vero_encryption_key_file in the Odoo server configuration '
            'and restart Odoo. Back up this key separately from the database.'
        ))
    try:
        return Fernet(key.encode('ascii'))
    except (ValueError, TypeError, UnicodeError):
        raise error(_('The Vero storage encryption key is invalid. Ask your administrator to check the server configuration.')) from None


class DatabasePath:
    """Internal blob address, never a filesystem path or an ORM field."""
    def __init__(self, store, name='.'):
        self.store = store
        self.name = str(PurePosixPath(name))

    def __truediv__(self, name):
        path = PurePosixPath(self.name) / name
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Invalid internal blob address')
        return type(self)(self.store, str(path))

    def exists(self):
        return self.name in self.store.files

    def read(self):
        return base64.b64decode(self.store.files[self.name], validate=True)

    def write(self, content):
        self.store.files[self.name] = base64.b64encode(content).decode('ascii')
        self.store.save()


class Vault:
    def __init__(self, cr, backend_id, company_id, environment, cipher, error):
        self.cr, self.backend_id, self.cipher, self.error = cr, backend_id, cipher, error
        self.binding = [backend_id, company_id, environment]
        self.files = {}
        self.settings = {}
        cr.execute('SELECT ciphertext FROM vero_api_secret WHERE backend_id=%s', [backend_id])
        row = cr.fetchone()
        self.existing = bool(row)
        if row:
            try:
                body = json.loads(cipher.decrypt(bytes(row[0])))
                if body['binding'] != self.binding or body['version'] != 1:
                    raise ValueError()
                self.files, self.settings = body['files'], body['settings']
                if not isinstance(self.files, dict) or not isinstance(self.settings, dict):
                    raise ValueError()
            except (InvalidToken, ValueError, KeyError, TypeError):
                raise error(_(
                    'The saved Vero credentials cannot be decrypted for this connection. '
                    'Restore the original server encryption key and matching database backup. '
                    'Do not overwrite the credentials or start a new certificate request.'
                )) from None
        self.root = DatabasePath(self)

    def save(self):
        body = {'version': 1, 'binding': self.binding, 'files': self.files, 'settings': self.settings}
        ciphertext = self.cipher.encrypt(json.dumps(body, separators=(',', ':')).encode())
        self.cr.execute('''INSERT INTO vero_api_secret (backend_id, ciphertext)
                           VALUES (%s, %s) ON CONFLICT (backend_id)
                           DO UPDATE SET ciphertext=EXCLUDED.ciphertext''', [self.backend_id, ciphertext])
        self.cr.commit()
        self.existing = True

    def configured(self, name):
        return name in self.files

    def get(self, name):
        return (self.root / name).read()

    def put(self, name, content):
        (self.root / name).write(content)


@contextmanager
def open_vault(registry, backend_id, company_id, environment, cipher, error):
    with registry.cursor() as cr:
        cr.execute('SELECT pg_try_advisory_lock(%s, %s)', [LOCK_NAMESPACE, backend_id])
        if not cr.fetchone()[0]:
            raise error(_('Another credential operation is in progress. Refresh the status shortly.'))
        try:
            cr.execute('SELECT company_id, environment FROM vero_api_backend WHERE id=%s', [backend_id])
            if cr.fetchone() != (company_id, environment):
                raise error(_('Save the Vero connection before configuring its credentials, then reopen this screen.'))
            yield Vault(cr, backend_id, company_id, environment, cipher, error)
        finally:
            cr.rollback()
            cr.execute('SELECT pg_advisory_unlock(%s, %s)', [LOCK_NAMESPACE, backend_id])
            cr.commit()
