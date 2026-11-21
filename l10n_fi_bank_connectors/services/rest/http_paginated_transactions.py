import logging

from abc import abstractmethod
from datetime import date
from typing import Callable, Optional

from ..base_banking_service import BankingServiceBase
from ..dtos import TransactionDTO
from ..error_handling.error_types import BankingError

_logger = logging.getLogger(__name__)


class HTTPPaginatedTransactions(BankingServiceBase):

    def get_transactions(self, account_id, date_from: date | None = None, date_to: date | None = None, max_pages: Optional[int] = None,) -> list[TransactionDTO]:
        """Fetch transactions for an account within an optional date range."""
        params = self._base_transaction_params()
        params.update(self._build_date_range_params(date_from, date_to))

        config = self._transaction_fetch_config(account_id)
        _logger.info(
            "%s: fetching transactions for account %s, params=%s",
            self.provider_name, account_id, params,
        )
        return self._fetch_transactions_pages(
            url=config["url"],
            params=params,
            account_id=account_id,
            get_next_token=config["get_next_token"],
            set_next_token=config["set_next_token"],
            max_pages=max_pages,
        )

    def _base_transaction_params(self) -> dict:
        """Non-date params sent with a transaction request (e.g. page size, order etc.)."""
        return {}

    def _fetch_transactions_pages(self,
        url: str,
        params: dict,
        account_id: str,
        get_next_token: Callable[[dict], Optional[str]],
        set_next_token: Callable[[dict, str], None],
        max_pages: Optional[int] = None,
    ) -> list[TransactionDTO]:
        """Generic pagination loop for transaction fetching."""
        _logger.info("_fetch_transactions_pages starting for account %s", account_id)
        results = []
        page = 0
        while True:
            data = self._get(url, params=params)
            page += 1
            for txn in self._get_transactions_from_response(data):
                dto = self._map_transaction(txn)
                if not self._should_include_transaction(dto):
                    continue
                results.append(dto)
            
            next_token = get_next_token(data)
            if not next_token:
                break
            if max_pages is not None and page >= max_pages:
                _logger.warning(
                    "Transaction pagination for account %s hit the configured "
                    "%d-page safety cap; stopping early with %d transactions "
                    "collected so far.", account_id, max_pages, len(results),
                )
                break
            set_next_token(params, next_token)
        return results
 

    @abstractmethod
    def _build_date_range_params(self, date_from: date | None, date_to: date | None) -> dict:
        """Convert a date range into this provider's request params."""
        pass

    @abstractmethod
    def _transaction_fetch_config(self, account_id: str) -> dict:
        """Return the provider-specific wiring needed to fetch transaction pages.

        Must return a dict with keys:
        - "url": the endpoint URL for this account
        - "get_next_token": Callable[[dict], Optional[str]]
        - "set_next_token": Callable[[dict, str], None]
        """
        pass

    @abstractmethod
    def _get_transactions_from_response(self, data: dict) -> list:
        """Extracts the raw transaction list from a page response."""
        pass