from cryptography.fernet import InvalidToken

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.constants.credentials import CredentialType
from ..utils.crypto import decrypt_fernet, encrypt_fernet


class OnlineBankingCredential(models.Model):
    _name = 'online.banking.credential'
    _description = 'Banking Credential'
    _order = 'connection_id, credential_type'

    connection_id = fields.Many2one(
        comodel_name='online.banking.connection',
        required=True,
        ondelete='cascade',
        index=True,
    )
    
    credential_type = fields.Selection(
        selection=CredentialType.SELECTION,
        string='Credential Type',
        required=True,
    )

    value_encrypted = fields.Text(
        string='Value',
        required=True,
    )
 
    expires_at = fields.Datetime(
        string='Expires At',
        help="Expiry for time-limited credentials.",
    )

    _sql_constraints = [
        (
            'unique_credential_per_connection',
            'UNIQUE(connection_id, credential_type)',
            'A credential of this type already exists for this connection.',
        ),
    ]

    def set_value(self, plain_value: str):
        """Encrypts and stores a credential value."""
        self.ensure_one()
        try:
            self.value_encrypted = encrypt_fernet(plain_value)
        except ValueError as e:
            raise UserError(_("Could not encrypt credential. Details: %s") % str(e)) from e

    def get_value(self) -> str:
        """Returns the decrypted credential value."""
        self.ensure_one()
        try:
            return decrypt_fernet(self.value_encrypted)
        except InvalidToken as e:
            raise UserError(
                _("Decryption failed. The encryption key in odoo.conf may be missing, incorrect, or the data is corrupted.")
            ) from e
        except Exception as e:
            raise UserError(
                _("Could not decrypt credential '%s' for connection '%s'. Details: %s")
                % (self.credential_type, self.connection_id.name, str(e))
            ) from e
