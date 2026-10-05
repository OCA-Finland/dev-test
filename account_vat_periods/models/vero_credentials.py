import hashlib
import logging
import re
from pathlib import Path
import uuid

from cryptography import x509
from cryptography.x509.oid import NameOID
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import config

from .. import vero_credentials as credentials
from .. import vero_payload
from .vero_backend import check_access

_logger = logging.getLogger(__name__)
_MANAGED_WRITE = object()
_PATH_FIELDS = {'software_key_file', 'certificate_file', 'private_key_file', 'authorization_token_file'}


class VeroBackendCredentials(models.Model):
    _inherit = 'vero.api.backend'

    def _credential_access(self):
        self.ensure_one()
        check_access(self)
        self.check_access('write')

    def _credential_store(self):
        self._credential_access()
        root = credentials.private_directory(Path(config['data_dir']) / 'vero_credentials')
        db = hashlib.sha256(self.env.cr.dbname.encode()).hexdigest()
        directory = credentials.private_directory(root / db)
        return credentials.private_directory(directory / f'company-{self.company_id.id}-backend-{self.id}-{self.environment}')

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

    def _credential_info(self):
        self._credential_access()
        directory = self._credential_store()
        enrollment = credentials.Enrollment(directory, self.environment, '', self.env.uid)
        with credentials.locked(directory):
            status = enrollment.status()
        phase = status.get('phase')
        messages = {
            'uncertain': _('The request has started. If no response is available, verify the outcome with the Finnish Tax Administration before trying again.'),
            'waiting': _('Request received. Wait at least 30 seconds, then retrieve the certificate.'),
            'ready': _('Certificate verified and ready for activation.'),
            'active': _('The certificate has been retrieved. Check the current certificate details and test the connection.'),
        }
        if phase == 'rejected':
            codes = ', '.join(re.findall(r'PKI\d{3}', status.get('message', '')))
            status['message'] = _('The Finnish Tax Administration rejected the request: %s', codes)
        elif phase in messages:
            status['message'] = messages[phase]
        result = {
            'name': self.name, 'company': self.company_id.display_name,
            'environment': self.environment, 'vat': self.company_id.vat or '',
            'key_configured': bool(self.software_key_file),
            'certificate_configured': bool(self.certificate_file and self.private_key_file),
            'enrollment': status,
        }
        if self.certificate_file:
            try:
                cert = x509.load_pem_x509_certificate(credentials.read_private(Path(self.certificate_file)))
                result['certificate'] = {
                    'subject': cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
                    'expires': cert.not_valid_after_utc.isoformat(),
                }
            except Exception:
                result['certificate_error'] = _('The current certificate details could not be read.')
        return result

    def action_credentials(self):
        self._credential_access()
        return {'type': 'ir.actions.client', 'tag': 'account_vat_periods.credentials',
                'name': _('Vero API: keys and certificate'), 'params': {'backend_id': self.id}}

    def _credential_operation(self, operation, values):
        """Private method: secret inputs must NEVER pass through call_kw/RPC logs."""
        self._credential_access()
        if operation == 'status':
            return self._credential_info()
        if operation == 'test_connection':
            code, data = self._call('GetVATPeriods/v1', {
                'BusinessId': self._credential_identity(), 'FilingYear': fields.Date.today().year,
            })
            if code != 200 or not isinstance(data, dict) or not isinstance(data.get('FilingPeriod'), list):
                raise credentials.CredentialError(_('The Vero API connection test failed. Check the environment, key, certificate and API permissions.'))
            result = self._credential_info()
            result['connection_ok'] = True
            return result
        if operation not in ('save_key', 'submit', 'retrieve', 'activate'):
            raise credentials.CredentialError(_('Unknown credential operation.'))
        # Serialize identity/path updates with this operation before filesystem
        # side effects. Files have their own lock because DB rollback is possible.
        self.env.cr.execute('SELECT id FROM vero_api_backend WHERE id=%s FOR UPDATE NOWAIT', [self.id])
        self.invalidate_recordset()
        directory = self._credential_store()
        with credentials.locked(directory):
            if operation == 'save_key':
                self._credential_mutation_allowed()
                key = values.get('software_key', '')
                if not isinstance(key, str) or not 16 <= len(key) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
                    raise credentials.CredentialError(_('The API key is missing or contains whitespace or invalid characters.'))
                path = directory / ('software-key-' + uuid.uuid4().hex + '.txt')
                credentials.save_private(path, key.encode())
                self.with_context(_vero_managed_credentials=_MANAGED_WRITE).write({'software_key_file': str(path)})
            else:
                enrollment = credentials.Enrollment(directory, self.environment, self._credential_identity(), self.env.uid)
                if operation == 'submit':
                    enrollment.submit(values.get('transfer_id', ''), values.get('transfer_password', ''), self.company_id.name)
                else:
                    state, generation = enrollment.retrieve()
                    if operation == 'activate':
                        self._credential_mutation_allowed()
                        self.with_context(_vero_managed_credentials=_MANAGED_WRITE).write({'certificate_file': str(generation / 'certificate.pem'),
                                    'private_key_file': str(generation / 'private-key.pem')})
                        # The filesystem state says validated, not necessarily committed.
                        # Status confirms activation from the DB pointer; repeat is safe.
                        state.update(phase='active', message='The certificate has been retrieved. Check the current certificate details and test the connection.')
                        enrollment.save(state)
            _logger.info('Vero credential operation=%s backend=%s company=%s user=%s environment=%s',
                         operation, self.id, self.company_id.id, self.env.uid, self.environment)
        return self._credential_info()

    def _check_credential_paths_write(self, vals):
        # A company accountant must not point their connection at another
        # company's files. Only the managed UI or technical administrators may
        # configure server paths. The identity token cannot be forged over RPC.
        if (_PATH_FIELDS.intersection(vals)
                and self.env.context.get('_vero_managed_credentials') is not _MANAGED_WRITE
                and not self.env.su and not self.env.user.has_group('base.group_system')):
            raise AccessError(_('Use Keys and certificate to configure credentials. Manual server paths require a technical administrator.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_credential_paths_write(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._check_credential_paths_write(vals)
        for backend in self:
            changes_identity = (('company_id' in vals and vals['company_id'] != backend.company_id.id)
                                or ('environment' in vals and vals['environment'] != backend.environment))
            if changes_identity and (backend.software_key_file or backend.certificate_file or backend.private_key_file):
                raise UserError(_('Create a separate connection to change the company or environment after configuring credentials.'))
            if changes_identity and (backend._credential_store() / 'enrollment.json').exists():
                raise UserError(_('Create a separate connection after starting certificate enrollment.'))
        return super().write(vals)
