import inspect
import logging
import re

from abc import ABC, abstractmethod

from odoo import _
from odoo.exceptions import UserError

from .constants.payments import SepaConstraints
from ..utils.formatting import to_decimal

_logger = logging.getLogger(__name__)

IBAN_PATTERN = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$')

class PaymentValidatorBase(ABC):
    """
    Base validator for SEPA payments. Enforces rules shared across all providers:
    currency, amount format, IBAN format, creditor/debtor name and IBAN presence.
    Provider-specific rules (field caps, reference requirements, instruction ID)
    are implemented in subclasses.
    """
    
    _amount_pattern: re.Pattern

    def __init__(self, payment):
        self._payment = payment
        self._errors = []
        
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls) and not hasattr(cls, '_amount_pattern'):
            raise TypeError(f"{cls.__name__} must define '_amount_pattern'")

    @abstractmethod
    def validate(self):
        pass

    def _run(self, *checks):
        for fn in checks:
            fn()
        if self._errors:
            _logger.warning(
                "Payment validation failed: %s",
                "; ".join(self._errors),
            )
            raise UserError(
                _("Payment validation failed:\n%s") %
                "\n".join(f"• {e}" for e in self._errors)
            )
    
    def _add(self, msg):
        self._errors.append(msg)

    # --- shared checks ---
    def _currency(self):
        if self._payment.currency != SepaConstraints.SUPPORTED_CURRENCY:
            self._add(_("Currency must be EUR. Got: '%s'.") % self._payment.currency)

    def _amount(self):
        amt = to_decimal(self._payment.amount)
        if amt <= 0:
            return self._add(_("Amount must be greater than zero."))
        fmt = f"{amt:.2f}"
        if not self._amount_pattern.match(fmt):
            self._add(_("Invalid amount format: '%s'.") % fmt)

    def _creditor(self):
        self._iban(self._payment.creditor_iban, _("Creditor IBAN"))
        self._name(self._payment.creditor_name, _("Creditor name"))

    def _debtor(self):
        self._iban(self._payment.debtor_iban, _("Debtor IBAN"))
        self._name(self._payment.debtor_name, _("Debtor name"))

    def _iban(self, v, label):
        if not v or not v.strip():
            return self._add(_("%s must not be empty.") % label)
        if not IBAN_PATTERN.match(v.replace(" ", "").upper()):
            self._add(_("%s '%s' is invalid IBAN.") % (label, v))

    def _name(self, v, label):
        if not v or not v.strip():
            return self._add(_("%s must not be empty.") % label)
        if len(v) > SepaConstraints.MAX_NAME_LENGTH:
            self._add(_("%s too long (%d): '%s'.") % (label, SepaConstraints.MAX_NAME_LENGTH, v))
