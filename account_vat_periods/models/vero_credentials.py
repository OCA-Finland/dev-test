"""Private credential operations; plaintext never crosses the ORM/RPC boundary."""
from contextlib import contextmanager
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import config

from .. import vero_credentials as credentials
from .. import vero_payload, vero_vault
from ..vero_transport import MemoryCertificate
from .vero_backend import check_access

_logger = logging.getLogger(__name__)
_PATH_FIELDS = {'software_key_file', 'certificate_file', 'private_key_file', 'authorization_token_file'}
_BLOBS = {'software_key_file': 'active/software-key', 'certificate_file': 'active/certificate.pem',
          'private_key_file': 'active/private-key.pem', 'authorization_token_file': 'active/authorization-token'}


class VeroBackendCredentials(models.Model):
    _inherit = 'vero.api.backend'

    def init(self):
        try:
            credentials.check_dependencies()
        except credentials.CredentialError as exc:
            raise UserError(exc.translated(self.env._)) from None
        super().init()
        # No ORM model: no generic search/read/export endpoint for ciphertext.
        self.env.cr.execute('''CREATE TABLE IF NOT EXISTS vero_api_secret (
            backend_id integer PRIMARY KEY REFERENCES vero_api_backend(id) ON DELETE CASCADE,
            ciphertext bytea NOT NULL)''')

    def _credential_access(self):
        self.ensure_one()
        check_access(self)
        self.check_access('write')

    def _legacy_credential_directory(self):
        db = hashlib.sha256(self.env.cr.dbname.encode()).hexdigest()
        return Path(config['data_dir']) / 'vero_credentials' / db / f'company-{self.company_id.id}-backend-{self.id}-{self.environment}'

    def _has_legacy_credentials(self):
        return any(self[name] for name in _PATH_FIELDS) or (self._legacy_credential_directory() / 'enrollment.json').exists()

    @contextmanager
    def _open_credential_vault(self):
        self._credential_access()
        cipher = vero_vault.cipher_from_config(config, credentials.CredentialError)
        with vero_vault.open_vault(self.env.registry, self.id, self.company_id.id, self.environment,
                                   cipher, credentials.CredentialError) as vault:
            yield vault

    def _credential_identity(self):
        try:
            return vero_payload.business_id(self.company_id.vat)
        except ValueError:
            raise credentials.CredentialError(_("Set the certificate holder's Finnish business ID or FI VAT number on the company before retrieval.")) from None

    def _credential_mutation_allowed(self):
        self._credential_access()
        if self.env['vero.api.submission'].search_count([
            ('report_id.backend_id', '=', self.id), ('state', 'in', ['queued', 'sending', 'uncertain']),
        ]):
            raise credentials.CredentialError(_('This connection has a pending or uncertain return. Resolve it before changing credentials.'))

    def _legacy_read(self, path):
        """Read-only migration: never chmod, follow links or delete source files."""
        path = Path(path)
        if not path.is_absolute() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise credentials.CredentialError(_('A legacy credential path is invalid or is a symbolic link. Ask your administrator to check it.'))
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise credentials.CredentialError(_('A legacy credential file is not a regular private file.'))
            if hasattr(os, 'getuid') and (info.st_uid != os.getuid() or info.st_mode & 0o022):
                raise credentials.CredentialError(_('A legacy credential file has an unsafe owner or write permissions. Ask your administrator to correct that file before migration.'))
            content = stream.read(credentials.MAX_RESPONSE + 1)
            if len(content) > credentials.MAX_RESPONSE:
                raise credentials.CredentialError(_('The secret file is too large.'))
            return content

    def _migrate_legacy_credentials(self, vault):
        if vault.existing:
            return
        files = {}
        for field, name in _BLOBS.items():
            if self[field]:
                files[name] = self._legacy_read(self[field])
        if bool(files.get('active/certificate.pem')) != bool(files.get('active/private-key.pem')):
            raise credentials.CredentialError(_('Both the legacy certificate and its private key are required for migration.'))
        if files.get('active/certificate.pem'):
            certificate = x509.load_pem_x509_certificate(files['active/certificate.pem'])
            key = serialization.load_pem_private_key(files['active/private-key.pem'], password=None)
            names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            if len(names) != 1 or names[0].value != self._credential_identity() or certificate.public_key().public_numbers() != key.public_key().public_numbers():
                raise credentials.CredentialError(_('The certificate does not match the company identifier or the key generated on the server.'))
        directory = self._legacy_credential_directory()
        if (directory / 'enrollment.json').exists():
            content = self._legacy_read(directory / 'enrollment.json')
            state = json.loads(content)
            generation = state.get('generation', '')
            if not re.fullmatch('[a-f0-9]{32}', generation) or state.get('identity') != self._credential_identity():
                raise credentials.CredentialError(_('The certificate retrieval state is invalid.'))
            files['enrollment.json'] = content
            for name in ('private-key.pem', 'request.csr', 'submit-response.xml', 'retrieve-response.xml', 'certificate.pem'):
                path = directory / generation / name
                if path.exists():
                    files[generation + '/' + name] = self._legacy_read(path)
            if generation + '/private-key.pem' not in files:
                raise credentials.CredentialError(_('The original private key for the pending certificate request is missing. Restore it before migration; do not start another request.'))
            key = serialization.load_pem_private_key(files[generation + '/private-key.pem'], password=None)
            if generation + '/request.csr' in files:
                csr = x509.load_pem_x509_csr(files[generation + '/request.csr'])
                names = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
                if not csr.is_signature_valid or len(names) != 1 or names[0].value != self._credential_identity() or csr.public_key().public_numbers() != key.public_key().public_numbers():
                    raise credentials.CredentialError(_('The certificate does not match the company identifier or the key generated on the server.'))
        vault.files.update({name: base64.b64encode(content).decode('ascii') for name, content in files.items()})
        vault.settings['migrated'] = True
        vault.save()

    def _credential_info(self):
        self._credential_access()
        result = {'name': self.name, 'company': self.company_id.display_name, 'environment': self.environment,
                  'vat': self.company_id.vat or '', 'key_configured': False, 'certificate_configured': False,
                  'legacy_available': False, 'storage_ready': False, 'enrollment': {}}
        try:
            with self._open_credential_vault() as vault:
                result['storage_ready'] = True
                result['legacy_available'] = not vault.existing and self._has_legacy_credentials()
                result['key_configured'] = vault.configured('active/software-key')
                result['certificate_configured'] = vault.configured('active/certificate.pem') and vault.configured('active/private-key.pem')
                if result['certificate_configured']:
                    certificate = x509.load_pem_x509_certificate(vault.get('active/certificate.pem'))
                    result['certificate'] = {'subject': certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
                                             'expires': certificate.not_valid_after_utc.isoformat()}
                result['enrollment'] = credentials.Enrollment(vault.root, self.environment, '', self.env.uid).status()
        except credentials.CredentialError as exc:
            result['enrollment'] = {'phase': 'blocked', 'message': exc.translated(self.env._)}
        except (OSError, ValueError, KeyError, TypeError):
            result['enrollment'] = {'phase': 'blocked', 'message': _('The saved Vero credential data could not be read. Ask your administrator to check the encrypted storage and its backup.')}
        status = result['enrollment']
        messages = {
            'uncertain': _('The request has started. If no response is available, verify the outcome with the Finnish Tax Administration before trying again.'),
            'waiting': _('Request received. Wait at least 30 seconds, then retrieve the certificate.'),
            'ready': _('Certificate verified and ready for activation.'),
            'active': _('The certificate has been retrieved. Check the current certificate details and test the connection.'),
        }
        if status.get('phase') == 'rejected':
            status['message'] = _('The Finnish Tax Administration rejected the request: %s', ', '.join(re.findall(r'PKI\d{3}', status.get('message', ''))))
        elif status.get('phase') in messages:
            status['message'] = messages[status['phase']]
        return result

    def action_credentials(self):
        self._credential_access()
        return {'type': 'ir.actions.client', 'tag': 'account_vat_periods.credentials',
                'name': _('Vero API: keys and certificate'), 'params': {'backend_id': self.id}}

    def _credential_operation(self, operation, values):
        self._credential_access()
        if operation == 'status':
            return self._credential_info()
        if operation in ('submit', 'retrieve', 'activate', 'test_connection', 'migrate'):
            credentials.check_dependencies()
        if operation == 'test_connection':
            code, data = self._call('GetVATPeriods/v1', {'BusinessId': self._credential_identity(), 'FilingYear': fields.Date.today().year})
            if code != 200 or not isinstance(data, dict) or not isinstance(data.get('FilingPeriod'), list):
                raise credentials.CredentialError(_('The Vero API connection test failed. Check the environment, key, certificate and API permissions.'))
            return dict(self._credential_info(), connection_ok=True)
        if operation not in ('save_key', 'submit', 'retrieve', 'activate', 'migrate'):
            raise credentials.CredentialError(_('Unknown credential operation.'))
        with self._open_credential_vault() as vault:
            if operation == 'migrate':
                self._migrate_legacy_credentials(vault)
            else:
                if not vault.existing and self._has_legacy_credentials():
                    raise credentials.CredentialError(_('Import the existing credentials into encrypted storage before changing keys or continuing certificate retrieval.'))
                if operation == 'save_key':
                    self._credential_mutation_allowed()
                    key = values.get('software_key', '')
                    if not isinstance(key, str) or not 16 <= len(key) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
                        raise credentials.CredentialError(_('The API key is missing or contains whitespace or invalid characters.'))
                    vault.put('active/software-key', key.encode())
                else:
                    enrollment = credentials.Enrollment(vault.root, self.environment, self._credential_identity(), self.env.uid)
                    if operation == 'submit':
                        enrollment.submit(values.get('transfer_id', ''), values.get('transfer_password', ''), self.company_id.name)
                    else:
                        state, generation = enrollment.retrieve()
                        if operation == 'activate':
                            self._credential_mutation_allowed()
                            vault.files['active/certificate.pem'] = vault.files[(generation / 'certificate.pem').name]
                            vault.files['active/private-key.pem'] = vault.files[(generation / 'private-key.pem').name]
                            state.update(phase='active', message='The certificate has been retrieved. Check the current certificate details and test the connection.')
                            enrollment.save(state)
            _logger.info('Vero credential operation=%s backend=%s company=%s user=%s environment=%s',
                         operation, self.id, self.company_id.id, self.env.uid, self.environment)
        return self._credential_info()

    def _transport_credentials(self):
        """Read one consistent credential snapshot for this HTTP request."""
        with self._open_credential_vault() as vault:
            if not vault.configured('active/software-key'):
                raise UserError(_('Configure or import the credentials through Keys and certificate.'))
            token = vault.get('active/authorization-token').decode().strip() if vault.configured('active/authorization-token') else None
            certificate = None
            if self.environment != 'sandbox':
                if not vault.configured('active/certificate.pem') or not vault.configured('active/private-key.pem'):
                    raise UserError(_('Retrieve and activate the certificate through Keys and certificate, or import the existing credentials.'))
                certificate = MemoryCertificate(vault.get('active/certificate.pem'), vault.get('active/private-key.pem'))
            return vault.get('active/software-key').decode().strip(), token, certificate

    def _check_credential_paths_write(self, vals):
        if _PATH_FIELDS.intersection(vals) and not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Use Keys and certificate to configure credentials. Manual server paths require a technical administrator.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_credential_paths_write(vals)
        return super().create(vals_list)

    def _lock_credential_identity(self):
        for backend in self:
            self.env.cr.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', [vero_vault.LOCK_NAMESPACE, backend.id])
            if not self.env.cr.fetchone()[0]:
                raise UserError(_('Another credential operation is in progress. Refresh the status shortly.'))

    def _has_encrypted_credentials(self):
        # A vault commit may be newer than the caller's repeatable-read snapshot.
        # The caller holds the identity lock while checking this fresh cursor.
        with self.env.registry.cursor() as cr:
            cr.execute('SELECT 1 FROM vero_api_secret WHERE backend_id=%s', [self.id])
            return bool(cr.fetchone())

    def write(self, vals):
        self._check_credential_paths_write(vals)
        self._lock_credential_identity()
        for backend in self:
            changes_identity = (('company_id' in vals and vals['company_id'] != backend.company_id.id)
                                or ('environment' in vals and vals['environment'] != backend.environment))
            if changes_identity or _PATH_FIELDS.intersection(vals):
                if backend._has_encrypted_credentials():
                    raise UserError(_('Encrypted credentials are bound to this company and environment. Create a separate connection instead of changing its identity or legacy file paths.'))
            if changes_identity and backend._has_legacy_credentials():
                raise UserError(_('Create a separate connection to change the company or environment after configuring credentials.'))
        return super().write(vals)

    def unlink(self):
        self._lock_credential_identity()
        for backend in self:
            if backend._has_encrypted_credentials() or backend._has_legacy_credentials():
                raise UserError(_('This connection has credentials or a certificate request. Archive it instead of deleting its recovery data.'))
        return super().unlink()
