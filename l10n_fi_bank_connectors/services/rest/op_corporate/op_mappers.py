from .constants.op_payments import OPPaymentStatus
from .op_dtos import OPAccountDTO, OPPaymentResponseDTO, OPTransactionDTO
from ....utils.formatting import (
    parse_date, 
    to_decimal, 
    map_status_or_unrecognized,
    normalize_iban
    )


class OPMappers:
    """Maps OP Corporate API responses to internal data transfer objects."""

    def _map_account(self, raw: dict) -> OPAccountDTO:
        """Convert raw account data to OPAccountDTO."""
        balance_val = raw.get("balance")
        product_names = raw.get("productNames", {})
        dto = OPAccountDTO(
            external_id=raw.get("surrogateId", ""),
            iban=normalize_iban(raw.get("iban", "")),
            bic=raw.get("bic", ""),
            currency=raw.get("currency", "EUR"),
            name=raw.get("name") or normalize_iban(raw.get("iban", "")),
            product=product_names.get("FI") or next(iter(product_names.values()), ""),
            balance=to_decimal(balance_val),
            raw=raw,
        )
        return dto
    
    def _map_transaction(self, raw: dict) -> OPTransactionDTO:
        """Convert raw transaction data to TransactionDTO."""
        amount = to_decimal(raw.get("amount", "0"))
        if amount < 0:
            account_number = raw.get("creditorAccount")
            partner_name = raw.get("creditorName")
        else:
            account_number = raw.get("debtorAccount")
            partner_name = raw.get("debtorName")

        return OPTransactionDTO(
            transaction_id=raw.get("objectId") or raw.get("archiveId"),
            booking_date=parse_date(raw.get("bookingDate")),
            value_date=parse_date(raw.get("valueDate")),
            transaction_type=None,      # OP API does not provide the field
            account_number=account_number,
            payment_ref=raw.get("reference") or "",
            ref=raw.get("message") or "",
            amount=amount,
            amount_currency=raw.get("currency", "EUR"),
            partner_name=partner_name,
            raw=raw,
            balance_before=to_decimal(raw.get("balanceBefore")),
            balance_after=to_decimal(raw.get("balanceAfter")),
        )
        
    def _map_payment_response(self, raw: dict) -> OPPaymentResponseDTO:
        """Convert raw payment response to OPPaymentResponseDTO."""
        error_info = raw.get("errorProcessingInfo") or {}
        return OPPaymentResponseDTO(
            error_message=error_info.get("message"),
            error_code=error_info.get("code"),
            status=map_status_or_unrecognized(OPPaymentStatus.TO_INTERNAL, raw.get("status", "")),
            message=raw.get("message", ""),
            reference=raw.get("reference", ""),
            raw=raw,
            banking_payment_id=raw.get("instructionId", "")
        )
