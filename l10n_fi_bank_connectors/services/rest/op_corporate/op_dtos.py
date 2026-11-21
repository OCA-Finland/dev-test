from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from odoo import _

from ...dtos import AccountDTO, PaymentRequestDTO, PaymentResponseDTO, TransactionDTO
from ...constants.payments import PaymentStatus

@dataclass
class OPAccountDTO(AccountDTO):
    """OP Corporate API account extras."""
    pass

@dataclass
class OPTransactionDTO(TransactionDTO):
    """OP Business API transaction extras."""
    balance_before: Optional[Decimal] = None

# Nordea does not allow VOP configuration, OP does. 
# For now, OP also hardcoded here, might want to implement full configuration in future.
@dataclass
class OPPaymentRequestDTO(PaymentRequestDTO):
    """OP Corporate payment request extras."""
    instruction_id: str = ""
    vop_processing_rules: str = "NO_MATCH"  # the payment gets processed even if the bank does not match the payee during the technical check
    allow_vop_errors: bool = True

@dataclass
class OPPaymentResponseDTO(PaymentResponseDTO):
    """OP Corporate payment response extras."""
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    
    def notification_context(self) -> dict:
        ctx = {}
        if self.error_message:
            ctx["error_message"] = self.error_message
        if self.error_code:
            ctx["error_code"] = self.error_code
        if self.status == PaymentStatus.REJECTED:
            ctx["user_instruction"] = _(
                "This payment has been permanently rejected by OP. "
            )
            if self.error_message:
                ctx["user_instruction"] += "\n" + self.error_message
            if self.error_code:
                ctx["user_instruction"] += "\n" + _("Error code: %(code)s", code=self.error_code)
        return ctx
