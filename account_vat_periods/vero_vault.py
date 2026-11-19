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


def initialize(cr):
    """Create one database key atomically; never replace it during upgrades."""
    cr.execute("ALTER TABLE vero_api_secret ADD COLUMN IF NOT EXISTS storage_mode varchar NOT NULL DEFAULT 'external'")
    cr.execute('''CREATE TABLE IF NOT EXISTS vero_api_master_key (
        id integer PRIMARY KEY CHECK (id=1), key bytea NOT NULL,
        production_database varchar NOT NULL)''')
    # Do not pass the plaintext master key through Odoo's SQL debug logger or
    # profiler hooks. The driver participates in the same install transaction.
    # Database-side statement/parameter logging must also exclude secret writes.
    cr._obj.execute('''INSERT INTO vero_api_master_key (id,key,production_database)
                  SELECT 1,%s,current_database()
                  WHERE NOT EXISTS (SELECT 1 FROM vero_api_secret WHERE storage_mode='database')
                  ON CONFLICT (id) DO NOTHING''',
               [Fernet.generate_key()])


def external_configured(config):
    return any(os.environ.get(name) for name in ('ODOO_VERO_ENCRYPTION_KEY', 'ODOO_VERO_ENCRYPTION_KEY_FILE')) or any(
        config.get(name) for name in ('vero_encryption_key', 'vero_encryption_key_file'))


def database_cipher(cr, error):
    cr.execute('SELECT key FROM vero_api_master_key WHERE id=1')
    row = cr.fetchone()
    if not row:
        raise error(_('The database encryption key is missing. Restore it with the database; do not generate a replacement for existing credentials.'))
    try:
        return Fernet(bytes(row[0]))
    except (ValueError, TypeError):
        raise error(_('The database encryption key is invalid. Restore the original database key.')) from None


def select_cipher(cr, backend_id, config, error):
    cr.execute('SELECT storage_mode FROM vero_api_secret WHERE backend_id=%s', [backend_id])
    row = cr.fetchone()
    mode = row[0] if row else ('external' if external_configured(config) else 'database')
    if mode not in ('external', 'database'):
        raise error(_('The credential storage format is unsupported. Update the module before continuing.'))
    return (database_cipher(cr, error) if mode == 'database' else cipher_from_config(config, error)), mode


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
    def __init__(self, cr, backend_id, company_id, environment, cipher, error, mode='external'):
        self.cr, self.backend_id, self.cipher, self.error = cr, backend_id, cipher, error
        self.binding = [backend_id, company_id, environment]
        self.mode = mode
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
                    'An administrator can recover them using the original encryption key or explicitly reset this connection. '
                    'Do not repeat a pending certificate request.'
                )) from None
        self.root = DatabasePath(self)

    def save(self):
        body = {'version': 1, 'binding': self.binding, 'files': self.files, 'settings': self.settings}
        ciphertext = self.cipher.encrypt(json.dumps(body, separators=(',', ':')).encode())
        self.cr.execute('''INSERT INTO vero_api_secret (backend_id, ciphertext, storage_mode)
                           VALUES (%s, %s, %s) ON CONFLICT (backend_id)
                           DO UPDATE SET ciphertext=EXCLUDED.ciphertext, storage_mode=EXCLUDED.storage_mode''',
                        [self.backend_id, ciphertext, self.mode])
        self.cr.commit()
        self.existing = True

    def configured(self, name):
        return name in self.files

    def get(self, name):
        return (self.root / name).read()

    def put(self, name, content):
        (self.root / name).write(content)


@contextmanager
def open_vault(registry, backend_id, company_id, environment, cipher, error, config=None, maintenance=None):
    with registry.cursor() as cr:
        cr.execute('SELECT pg_try_advisory_lock(%s, %s)', [LOCK_NAMESPACE, backend_id])
        if not cr.fetchone()[0]:
            raise error(_('Another credential operation is in progress. Refresh the status shortly.'))
        try:
            cr.execute('SELECT company_id, environment FROM vero_api_backend WHERE id=%s', [backend_id])
            if cr.fetchone() != (company_id, environment):
                raise error(_('Save the Vero connection before configuring its credentials, then reopen this screen.'))
            if maintenance:
                yield cr
            else:
                mode = 'external'
                if cipher is None:
                    cipher, mode = select_cipher(cr, backend_id, config or {}, error)
                yield Vault(cr, backend_id, company_id, environment, cipher, error, mode)
        finally:
            cr.rollback()
            cr.execute('SELECT pg_advisory_unlock(%s, %s)', [LOCK_NAMESPACE, backend_id])
            cr.commit()
