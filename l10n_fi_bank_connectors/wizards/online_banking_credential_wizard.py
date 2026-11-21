import logging

from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.auth.token_cache import invalidate_token_cache
from ..services.constants.connection import cache_key
from ..services.constants.credentials import CredentialType
from ..services.rest.op_corporate.op_cert_cache import invalidate_cert_cache as invalidate_op_cert_cache
from ..services.soap.nordea_corporate_access.nordea_ca_cert_cache import invalidate_cert_cache as invalidate_nca_cert_cache
from ..utils.clock import to_odoo_utc_datetime
from ..utils.crypto import parse_cert_expiry, load_rsa_private_key, load_x509_certificate

_logger = logging.getLogger(__name__)


class OnlineBankingCredentialWizard(models.TransientModel):
    """Wizard for setting or updating banking credentials on a connection."""
    _name = 'online.banking.credential.wizard'
    _description = 'Set Banking Credential'

    _VALIDATION_RULES = (
        ('PEM_TYPES', '_validate_pem_input'),
        ('SIGNING_KEY_TYPES', '_validate_signing_key'),
        ('CERT_TYPES', '_validate_cert'),
    )

    connection_id = fields.Many2one(
        comodel_name = 'online.banking.connection',
        required = True,
        readonly = True,
    )
    
    credential_type = fields.Selection(
        selection = CredentialType.SELECTION,
        required = True,
        readonly = True,
    )

    credential_label = fields.Char(
        compute = '_compute_credential_label',
    )
    
    is_pem = fields.Boolean(
        compute = '_compute_credential_label',
    )
    
    credential_value = fields.Text(
        string = "Value",
    )
    
    is_set = fields.Boolean(
        compute = '_compute_is_set',
        string = "Currently set",
    )

    @api.depends('credential_type')
    def _compute_credential_label(self):
        """Compute the label and PEM flag based on credential type."""
        for rec in self:
            rec.credential_label = CredentialType.LABELS.get(rec.credential_type, '')
            rec.is_pem = rec.credential_type in CredentialType.PEM_TYPES

    @api.depends('connection_id', 'credential_type')
    def _compute_is_set(self):
        """Check if the credential is already set on the connection."""
        for rec in self:
            if not rec.connection_id or not rec.credential_type:
                rec.is_set = False
                continue
            rec.is_set = bool(rec.connection_id.credential_ids.filtered(
                lambda c: c.credential_type == rec.credential_type
            ))
    
    # action
    def action_save(self):
        """Validate, save the credential, and close the wizard."""
        self.ensure_one()
        self._validate()
        self._upsert_credential()
        self.write({'credential_value': False}) # Clear the field to avoid keeping sensitive data in memory
        self.connection_id.invalidate_recordset(['credential_ids'])
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Saved"),
                "message": _("'%s' has been saved successfully.") % self.credential_label,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
    
    # validation
    def _validate(self):
        """Run all validations for the credential input."""
        self.ensure_one()
        
        # empty
        if not self.credential_value or not self.credential_value.strip():
            raise UserError(_("Enter a value before saving."))
        
        for type_set_name, method_name in self._VALIDATION_RULES:
            type_set = getattr(CredentialType, type_set_name)
            if self.credential_type in type_set:
                getattr(self, method_name)()
    
        
    def _validate_pem_input(self):
        """Validate that PEM-formatted credentials start correctly."""
        if not self.credential_value.strip().startswith('-----BEGIN'):
            raise UserError(
                _("'%s' should start with '-----BEGIN ...'.")
                % self.credential_label
            )
            
    def _validate_signing_key(self):
        """Validate that signing keys are valid RSA private keys."""
        try:
            load_rsa_private_key(self.credential_value.strip())
        except ValueError as e:
            raise UserError(
                _("The signing key could not be loaded. Ensure it is a valid PEM-encoded RSA private key.")
            ) from e

    def _validate_cert(self):
        """Validate X.509 certificate credentials."""
        try:
            load_x509_certificate(self.credential_value.strip())
        except ValueError as e:
            raise UserError(
                _("The certificate could not be loaded. Ensure it is a valid PEM-encoded X.509 certificate.")
            ) from e


    # helpers
    def _extract_expiry(self) -> datetime | None:
        """Extract expiry date from certificate credentials.

        Only covers CERT_TYPES (parsed from the PEM). REFRESH_TOKEN expiry is set separately, 
        in NordeaOAuthWizard._update_refresh_token_expiry(), from the OAuth consent `duration`.
        """
        if self.credential_type in CredentialType.CERT_TYPES:
            return parse_cert_expiry(self.credential_value.strip())
        return None

    def _upsert_credential(self):
        """Create or update the credential record."""
        expires_at = self._extract_expiry()
        existing = self._find_existing_credential()

        if existing:
            self._update_credential(existing, expires_at)
        else:
            self._create_credential(expires_at)

        self._clear_connection_caches()

        _logger.info(
            "Saved credential '%s' for connection '%s'",
            self.credential_type, self.connection_id.name,
        )
        
    def _find_existing_credential(self):
        return self.env['online.banking.credential'].search([
            ('connection_id', '=', self.connection_id.id),
            ('credential_type', '=', self.credential_type),
        ], limit=1)
    
    def _create_credential(self, expires_at):
        credential = self.env['online.banking.credential'].create({
            'connection_id': self.connection_id.id,
            'credential_type': self.credential_type,
            'value_encrypted': 'placeholder',
        })
        credential.set_value(self.credential_value.strip())
        if expires_at is not None:
            credential.expires_at = to_odoo_utc_datetime(expires_at)

    def _update_credential(self, credential, expires_at):
        credential.set_value(self.credential_value.strip())
        if expires_at is not None:
            credential.expires_at = to_odoo_utc_datetime(expires_at)

    def _clear_connection_caches(self):
        """Invalidate token and cert caches."""
        key = cache_key(self.connection_id)
        invalidate_token_cache(key)

        if self.credential_type in (
            CredentialType.OP_MTLS_CERT_PEM,
            CredentialType.OP_MTLS_KEY_PEM,
        ):
            invalidate_op_cert_cache(key)
            
        elif self.credential_type in (
            CredentialType.NORDEA_CA_CERT_PEM,
            CredentialType.NORDEA_CA_KEY_PEM,
        ):
            invalidate_nca_cert_cache(key)
        _logger.debug(
            "Caches invalidated for connection '%s' after credential update.",
            self.connection_id.name,
        )
