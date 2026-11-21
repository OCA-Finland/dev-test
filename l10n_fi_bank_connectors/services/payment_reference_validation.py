from odoo import _
from odoo.exceptions import UserError

from ..utils.payment_refs import validate_rf_reference, validate_viitenumero


class PaymentReferenceValidation:
    """Validates user-supplied payment references (RF / Finnish viitenumero)."""

    def validate_payment_reference(self, payment_ref: str) -> None:
        """Validate a user-supplied payment reference against RF / viitenumero format."""
        if payment_ref and not validate_rf_reference(payment_ref) and not validate_viitenumero(payment_ref):
            raise UserError(_("Payment reference '%s' is not a valid RF reference or Finnish viitenumero.") % payment_ref)