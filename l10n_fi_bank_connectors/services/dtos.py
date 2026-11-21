from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class ReconciliationField(Enum):
    """
    Fields on TransactionDTO consumed by account_reconcile_model_oca in the OCA reconciliation module for reconciliation matching.
    We are listing them bc the parent module has no guards against None when processing them, 
    and TransactionDTO.__post_init__ must default them to ""
    """
    PAYMENT_REF = "payment_ref"
    REF = "ref"
    AMOUNT = "amount"
    AMOUNT_CURRENCY = "amount_currency"
    ACCOUNT_NUMBER = "account_number"

    @classmethod
    def null_safe_fields(cls) -> frozenset["ReconciliationField"]:
        """Fields that have no guard against None."""
        return frozenset({cls.PAYMENT_REF, cls.REF})



@dataclass
class AccountDTO:
    """Shared base for all provider account DTOs."""
    external_id: str        # technical id that each API uses in further requests 
    iban: str
    currency: str
    name: str
    raw: dict = field(default_factory=dict)
    bic: str = ""
    account_number: Optional[str] = None
    balance: Optional[Decimal] = None
    product: str = ""

@dataclass
class TransactionDTO:
    """
    Shared fields for all provider transaction DTOs based on the columns
    in the account_bank_statement_line table. Full response is stored in the raw_data column.
    """
    # account_bank_statement_line fields
    amount: Decimal
    transaction_id: Optional[str] = None
    booking_date: Optional[date] = None
    value_date: Optional[date] = None
    transaction_type: Optional[str] = None
    account_number: Optional[str] = None
    payment_ref: str = ""
    ref: str = ""
    amount_currency: str = ""
    partner_name: str = ""
    raw: dict = field(default_factory=dict)
    # auxiliary fields
    balance_after: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in ("booking_date", "value_date"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, date) or isinstance(value, datetime)
            ):
                raise TypeError(
                    f"{field_name} must be a date or None, "
                    f"got {type(value).__name__}"
                )
            
        for rf in ReconciliationField.null_safe_fields():
            if getattr(self, rf.value) is None:
                setattr(self, rf.value, "")

        # unique_import_id (with UNIQUE constraint) is derived from transaction_id, an empty string would throw an IntegrityError.
        if self.transaction_id == "":
            self.transaction_id = None


@dataclass
class PaymentRequestDTO:
    """Base payment request. Contains only fields that every provider supports."""
    creditor_name: str
    creditor_iban: str
    debtor_iban: str
    debtor_name: str
    amount: Decimal
    currency: str
    reference: str = ""
    message: str = ""
    request_execution_date: Optional[date] = None

@dataclass
class PaymentResponseDTO:
    """
    Base payment response. Contains only fields that every provider returns.
    For now also used for the payment status endpoints, which return similar fields.
    """
    status: str
    reference: str = ""
    message: str = ""
    raw: dict = field(default_factory=dict)
    banking_payment_id: str = ""
    raw_bytes: Optional[bytes] = field(default=None, repr=False)
    
    def notification_context(self) -> dict:
        return {}