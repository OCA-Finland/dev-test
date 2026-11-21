from datetime import timedelta

from odoo import _, fields, api, models

from ..services.constants.credentials import CredentialType
from ..services.constants.connection import EXPIRY_WARN_DAYS


class OnlineBankingConnectionCredentials(models.Model):
    _inherit = 'online.banking.connection'
    
    client_id_set = fields.Boolean(
        string="Client ID Set",
        compute="_compute_credential_flags",
    )
    client_secret_set = fields.Boolean(
        string="Client Secret Set",
        compute="_compute_credential_flags",
    )
    op_mtls_cert_set = fields.Boolean(
        string="OP mTLS Certificate Set",
        compute="_compute_credential_flags",
    )
    op_mtls_key_set = fields.Boolean(
        string="OP mTLS Private Key Set",
        compute="_compute_credential_flags",
    )
    op_payment_signing_key_set = fields.Boolean(
        string="OP Payment Signing Key Set",
        compute="_compute_credential_flags",
    )
    op_payment_signing_kid_set = fields.Boolean(
        string="OP Payment Signing KID Set",
        compute="_compute_credential_flags",
    )
    nordea_auth_signing_key_set = fields.Boolean(
        string="Nordea Auth Signing Key Set",
        compute="_compute_credential_flags",
    )
    refresh_token_set = fields.Boolean(
        string="Refresh Token Set",
        compute="_compute_credential_flags",
    )

    nca_cert_set = fields.Boolean(
        string="Nordea Corporate Access Certificate Set",
        compute="_compute_credential_flags",
    )
    nca_key_set = fields.Boolean(
        string="Nordea Corporate Access Private Key Set",
        compute="_compute_credential_flags",
    )
    nca_signer_id_set = fields.Boolean(
        string="Nordea Corporate Access Signer ID Set",
        compute="_compute_credential_flags",
    )
    nca_sender_id_set = fields.Boolean(
        string="Nordea Corporate Access Sender ID Set",
        compute="_compute_credential_flags",
    )
    
    # expiration to be properly implemented in future
    credentials_expiry_warning = fields.Char(
        string="Credential Expiry Warning",
        compute="_compute_credentials_expiry_warning",
    )
    
    @api.depends('credential_ids', 'credential_ids.credential_type')
    def _compute_credential_flags(self):
        for rec in self:
            creds = rec.credential_ids.mapped('credential_type')
            rec.client_id_set = CredentialType.CLIENT_ID in creds
            rec.client_secret_set = CredentialType.CLIENT_SECRET in creds
            rec.refresh_token_set = CredentialType.REFRESH_TOKEN in creds
            rec.op_mtls_cert_set = CredentialType.OP_MTLS_CERT_PEM in creds
            rec.op_mtls_key_set = CredentialType.OP_MTLS_KEY_PEM in creds
            rec.op_payment_signing_key_set = CredentialType.OP_PAYMENT_SIGNING_KEY in creds
            rec.op_payment_signing_kid_set = CredentialType.OP_PAYMENT_SIGNING_KID in creds
            rec.nordea_auth_signing_key_set = CredentialType.NORDEA_AUTH_SIGNING_KEY in creds
            rec.nca_cert_set = CredentialType.NORDEA_CA_CERT_PEM in creds
            rec.nca_key_set = CredentialType.NORDEA_CA_KEY_PEM in creds
            rec.nca_signer_id_set = CredentialType.NORDEA_CA_SIGNER_ID in creds
            rec.nca_sender_id_set = CredentialType.NORDEA_CA_SENDER_ID in creds
            
    @api.depends('credential_ids', 'credential_ids.expires_at')
    def _compute_credentials_expiry_warning(self):
        warn_threshold = fields.Datetime.now() + timedelta(days=EXPIRY_WARN_DAYS)
        now = fields.Datetime.now()

        for rec in self:
            expiring = rec.credential_ids.filtered(
                lambda c: (
                    c.credential_type in CredentialType.HAS_EXPIRY
                    and c.expires_at
                    and c.expires_at <= warn_threshold
                )
            )
            if not expiring:
                rec.credentials_expiry_warning = False
                continue

            parts = []
            for cred in expiring:
                label = CredentialType.LABELS.get(cred.credential_type, cred.credential_type)
                if cred.expires_at <= now:
                    parts.append(_("'%s' has expired.") % label)
                else:
                    days_left = (cred.expires_at - now).days
                    parts.append(_("'%s' expires in %d day(s).") % (label, days_left))
            rec.credentials_expiry_warning = "  ".join(parts)
    
    def _get_credential(self, credential_type: str) -> str:
        self.ensure_one()
        credential = self.credential_ids.filtered(
            lambda c: c.credential_type == credential_type
        )
        if not credential:
            return ""
        return credential[0].get_value()
        
    @property
    def client_id_decrypted(self) -> str:
        return self._get_credential(CredentialType.CLIENT_ID)

    @property
    def client_secret_decrypted(self) -> str:
        return self._get_credential(CredentialType.CLIENT_SECRET)

    @property
    def op_payment_signing_key_decrypted(self) -> str:
        return self._get_credential(CredentialType.OP_PAYMENT_SIGNING_KEY)

    @property
    def op_payment_signing_kid_decrypted(self) -> str:
        return self._get_credential(CredentialType.OP_PAYMENT_SIGNING_KID)

    @property
    def op_mtls_cert_pem_decrypted(self) -> str:
        return self._get_credential(CredentialType.OP_MTLS_CERT_PEM)

    @property
    def op_mtls_key_pem_decrypted(self) -> str:
        return self._get_credential(CredentialType.OP_MTLS_KEY_PEM)

    @property
    def nordea_auth_signing_key_decrypted(self) -> str:
        return self._get_credential(CredentialType.NORDEA_AUTH_SIGNING_KEY)

    @property
    def refresh_token_decrypted(self) -> str:
        return self._get_credential(CredentialType.REFRESH_TOKEN)

    @property
    def nca_cert_pem_decrypted(self) -> str:
        return self._get_credential(CredentialType.NORDEA_CA_CERT_PEM)

    @property
    def nca_key_pem_decrypted(self) -> str:
        return self._get_credential(CredentialType.NORDEA_CA_KEY_PEM)

    @property
    def nca_signer_id_decrypted(self) -> str:
        return self._get_credential(CredentialType.NORDEA_CA_SIGNER_ID)

    @property
    def nca_sender_id_decrypted(self) -> str:
        return self._get_credential(CredentialType.NORDEA_CA_SENDER_ID)
