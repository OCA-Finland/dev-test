import re

from odoo import _

from .constants.op_payments import OPPaymentLimits
from ...payment_validator import PaymentValidatorBase

_INSTRUCTION_ID_PATTERN = re.compile(r'^[a-zA-Z0-9]{1,35}$')

class OPPaymentValidator(PaymentValidatorBase):
    """
    Validator for OP Corporate API payments.
    OP API payments require: instruction ID, reference (max 25), message (max 140),
    and that at least one of reference or message is present.
    """
    _amount_pattern = re.compile(r'^\d{1,13}\.\d{2}$')
    
    def validate(self):
        self._run( self._currency, self._amount, self._creditor, self._debtor, self._instruction_id, self._reference, self._message, self._reference_or_message,)
        
    def _instruction_id(self):
        v = self._payment.instruction_id
        if not v:
            return self._add(_("Instruction ID must not be empty."))
        if not _INSTRUCTION_ID_PATTERN.match(v):
            self._add(_("Invalid Instruction ID '%s'.") % v)

    def _reference(self):
        v = self._payment.reference or ""
        if v and len(v) > OPPaymentLimits.MAX_REFERENCE_LENGTH:
            self._add(
                _("Reference exceeds maximum length of %d characters: '%s'.") %
                (OPPaymentLimits.MAX_REFERENCE_LENGTH, v)
            )

    def _message(self):
        v = self._payment.message or ""
        if v and len(v) > OPPaymentLimits.MAX_MESSAGE_LENGTH:
            self._add(
                _("Message exceeds maximum length of %d characters.") %
                OPPaymentLimits.MAX_MESSAGE_LENGTH
            )

    def _reference_or_message(self):
        if not (self._payment.reference or "").strip() and \
           not (self._payment.message or "").strip():
            self._add(_("Either a reference or a message must be provided."))
