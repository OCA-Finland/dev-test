import re

from odoo import _

from ...payment_validator import PaymentValidatorBase
from .constants.nordea_payments import NordeaFIPaymentLimits

_RF_PATTERN = re.compile(r'^RF\d{2}[A-Z0-9]{1,21}$')

class NordeaFIPaymentValidator(PaymentValidatorBase):
    """
    Validator for Nordea FI SEPA payments.
    Nordea API payments require (FI only implementation): creditor message length (max 140).
    if reference present and starts with 'RF', must be valid RF format.
    """
    _amount_pattern = re.compile(r'^\d{1,9}\.\d{2}$')
    
    def validate(self):
        self._run( self._currency, self._amount, self._creditor, self._debtor, self._creditor_message, self._rf_reference,)
    
    def _creditor_message(self):
        v = self._payment.message or ""
        if v and len(v) > NordeaFIPaymentLimits.MAX_CREDITOR_MESSAGE_LENGTH:
            self._add(
                _("Creditor message exceeds maximum length of %d characters.") %
                NordeaFIPaymentLimits.MAX_CREDITOR_MESSAGE_LENGTH
            )

    def _rf_reference(self):
        v = (self._payment.reference or "").strip()
        if not v:
            return
        if v.upper().startswith("RF") and not _RF_PATTERN.match(v.upper()):
            self._add(_("RF reference '%s' has invalid format.") % v)
