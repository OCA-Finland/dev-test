from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .dtos import (
    AccountDTO, 
    PaymentRequestDTO, 
    PaymentResponseDTO, 
    TransactionDTO
    )

"""A base class for banking services, defines common DTOs and interfaces for AIS and PIS operations."""
@dataclass
class ProviderBackend:
    key: str
    label: str      # provider name + marked if sandbox
    sandbox: bool
    family: str = ""
    
    @staticmethod
    def make_pair(key: str, provider_name: str) -> tuple["ProviderBackend", "ProviderBackend"]:
        """Factory method to create a pair of sandbox and prod provider backends."""
        return (
            ProviderBackend(f"{key}_sandbox", f"{provider_name} (Sandbox)", sandbox=True, family=key),
            ProviderBackend(f"{key}_prod", f"{provider_name}", sandbox=False, family=key),
        )

    def as_choice(self) -> tuple[str, str]:
        """Returns a tuple with the provider and label. Used in dropdowns in UI."""
        return (self.key, self.label)
    
    def make_service_key(self, connection_id: int) -> str:
        """Returns a unique string identifier."""
        return f"{self.key}_{connection_id}"


class BankingServiceBase(ABC):
    TRANSACTION_HISTORY_LIMIT_DAYS: int | None = None       # how many days back an API keeps transaction records
    TRANSACTION_LOOKBACK_DAYS: int = 0                      # how many days back we keep pulling transactions
    APPLY_LOOKBACK_TO_MANUAL_PULLS: bool = True             # this is an ugly temporary solution


    # ----------------------------------------------------------
    # AIS
    # ----------------------------------------------------------
    @abstractmethod
    def get_accounts(self) -> list[AccountDTO]:
        """Return all accounts."""
        pass

    def refresh_accounts(self) -> list[AccountDTO]:
        """Return accounts for a scheduled or manual refresh.
        Defaults to get_accounts(). Services without a remote account feed
        raise AccountRefreshNotSupported."""
        return self.get_accounts()

    @abstractmethod
    def get_transactions(self, account_id, date_from: date | None = None, date_to: date | None = None, max_pages: Optional[int] = None,) -> list[TransactionDTO]:
        """Fetch transactions for an account within an optional date range."""

    def _should_include_transaction(self, dto: TransactionDTO) -> bool:
        """Decide if a fetched transaction should be imported. Currently used to filter out Nordea transactions with unbilled status."""
        return True

    # TODO method name and docs do not match
    def filter_transactions(self, transaction_dtos: list[TransactionDTO], date_from: date, date_to: date) -> list[TransactionDTO]:
        """Implement changes to the fetched transactions. No changes by default."""
        return transaction_dtos

    @abstractmethod
    def build_statement_values(self, transaction_dtos: list[TransactionDTO]) -> dict:
        """Build values needed to create/update a statement, e.g. balance_start, balance_end_real etc."""
        pass

    def _get_balance_values(self, account_id: str, include_balances: bool) -> dict:
        """Optionally return balance_end_real for the statement being built. No-op by default."""
        return {}

    
    # ----------------------------------------------------------
    # PIS
    # ----------------------------------------------------------
    @abstractmethod
    def initiate_payment(self, payment: PaymentRequestDTO) -> PaymentResponseDTO:
        """Submit a SEPA Credit Transfer."""
        pass
    
    @abstractmethod
    def get_payment_status(self, banking_payment_id: str) -> PaymentResponseDTO:
        """Return the status of an initiated payment."""
        pass
    
    def generate_unique_identification(self, payment) -> None:
        """Generate and persist a provider-specific banking_payment_id."""
        pass
    
    def validate_payment_reference(self, payment_ref: str) -> None:
        """Validate a user-supplied payment reference."""
        pass

    def supports_status_polling(self) -> bool:
        """
        True for providers with a payment status endpoint worth polling on a cron. 
        Currently true for OP API and Nordea API, false for NCA.
        """
        return True

    # ----------------------------------------------------------
    # Mappings
    # ----------------------------------------------------------
    @abstractmethod
    def _map_account(self, raw: dict) -> AccountDTO:
        """Map a raw API account response to a provider-specific AccountDTO subclass."""
        pass
    
    @abstractmethod
    def _map_transaction(self, raw: dict) -> TransactionDTO:
        """Map a raw API transaction response to a provider-specific TransactionDTO subclass."""
        pass

    def payment_request_dto_class(self) -> type[PaymentRequestDTO]:
        """Return the PaymentRequestDTO subclass this provider expects. Defaults to the base class."""
        return PaymentRequestDTO

    def extra_payment_request_kwargs(self, payment) -> dict:
        """Return provider-specific extra kwargs for building this provider's PaymentRequestDTO. Empty by default."""
        return {}

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of the service."""
        pass
