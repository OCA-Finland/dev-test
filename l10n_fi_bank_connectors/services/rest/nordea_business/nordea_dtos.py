from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from odoo import _

from ...dtos import AccountDTO, PaymentRequestDTO, PaymentResponseDTO, TransactionDTO
from ...constants.payments import PaymentStatus

@dataclass
class NordeaAccountDTO(AccountDTO):
    """Nordea Business API account extras."""
    available_balance: Optional[Decimal] = None
    value_dated_balance: Optional[Decimal] = None
    account_type: str = ""
    status: str = ""
    credit_limit: Optional[Decimal] = None
    country: str = ""
    latest_transaction_booking_date: Optional[date] = None

@dataclass
class NordeaTransactionDTO(TransactionDTO):
    """Nordea Business API transaction extras."""
    status: str = ""

@dataclass
class NordeaPaymentRequestDTO(PaymentRequestDTO):
    """Nordea payment request extras."""
    pass 
    
@dataclass
class NordeaPaymentResponseDTO(PaymentResponseDTO):
    """Nordea payment response extras."""
    signing_url:Optional[str] = None
    status_reason: Optional[str] = None
    reason_narrative: Optional[str] = None
    tpp_messages: list[dict] = field(default_factory=list)
    
    def notification_context(self) -> dict:
        ctx = {}
        if self.signing_url:
            ctx["signing_url"] = self.signing_url
        if self.tpp_messages:
            ctx["tpp_messages"] = self.tpp_messages
        instruction = self._build_user_instruction()
        if instruction:
            ctx["user_instruction"] = instruction
        return ctx
    
    def _build_user_instruction(self) -> str:
        status = self.status
        
        if status == PaymentStatus.PENDING_USER_APPROVAL:
            parts = [_("Please complete the signing process to approve this payment.")]
            if self.signing_url:
                parts.append(_("Signing URL: %s", self.signing_url))
            return "\n".join(parts)
        
        if status == PaymentStatus.ON_HOLD:
            return _(
                "Your payment has been put on hold by Nordea, for example due to fraud suspicion. "
                "Please contact Nordea directly or check for an SMS requesting confirmation."
            )
            
        if status == PaymentStatus.USER_APPROVAL_FAILED:
            parts = [_("The signing process failed. Please try again.")]
            if self.reason_narrative:
                parts.append(self.reason_narrative)
            return "\n".join(parts)
            
        if status == PaymentStatus.USER_APPROVAL_TIMEOUT:
            return _(
                "The signing window expired. Please restart the signing process."
            )

        if status == PaymentStatus.USER_APPROVAL_CANCELLED:
            return _(
                "The signing was cancelled. "
                "Please restart the signing process if you wish to proceed."
            )
            
        if status == PaymentStatus.LIMIT_EXCEEDED:
            return _(
                "A payment limit has been exceeded. "
                "You may retry after the limit resets, or contact Nordea to raise the limit."
            )
            
        if status == PaymentStatus.INSUFFICIENT_FUNDS:
            return _(
                "The payment was rejected due to insufficient funds."
            )

        if status == PaymentStatus.REJECTED:
            return self._build_rejection_instruction()

        return ""


    def _build_rejection_instruction(self) -> str:
            _REASON_INSTRUCTIONS = {
                "InsufficientFunds": _(
                    "The payment was rejected due to insufficient funds. "
                ),
                "InvalidCreditorAccount": _(
                    "The payment was rejected because the recipient account is invalid. "
                ),
                "PaymentDeclinedPsuShouldContactNordea": _(
                    "The payment was declined by Nordea. "
                    "Please contact Nordea directly to resolve this."
                ),
                "PaymentExecutionFailed": _(
                    "The payment execution failed. "
                ),
                "PaymentLimitExceeded": _(
                    "The payment was rejected because a payment limit was exceeded. "
                ),
                "RequiresSinglePaymentSigning": _(
                    "This payment requires individual signing and cannot be processed as part of a batch. "
                ),
            }
    
            parts = []
    
            reason_text = _REASON_INSTRUCTIONS.get(self.status_reason) if self.status_reason else None
            if reason_text:
                parts.append(reason_text)
            elif self.reason_narrative:
                parts.append(self.reason_narrative)
    
            tpp_lines = [m.get("text", "") for m in self.tpp_messages if m.get("text")]
            if tpp_lines:
                parts.extend(tpp_lines)
    
            return "\n".join(p for p in parts if p)