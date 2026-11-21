from .constants.nordea_transactions import NordeaTransactionStatus
from .constants.nordea_auth_config import PROVIDER_NAME
from .constants.nordea_api import (
    TRANSACTION_HISTORY_LIMIT_DAYS as NORDEA_TRANSACTION_HISTORY_LIMIT_DAYS,
    TRANSACTION_LOOKBACK_DAYS as NORDEA_TRANSACTION_LOOKBACK_DAYS
    )
from ...dtos import TransactionDTO
from ...error_handling import NordeaBusinessErrorHandler
from ..http_paginated_transactions import HTTPPaginatedTransactions
from .nordea_ais import NordeaAIS
from .nordea_auth import NordeaAuth
from .nordea_http import NordeaHTTPClient
from .nordea_mappers import NordeaMappers
from .nordea_pis import NordeaPIS


class NordeaBusinessService(NordeaMappers, NordeaAIS, NordeaPIS, HTTPPaginatedTransactions):
    TRANSACTION_HISTORY_LIMIT_DAYS = NORDEA_TRANSACTION_HISTORY_LIMIT_DAYS
    TRANSACTION_LOOKBACK_DAYS = NORDEA_TRANSACTION_LOOKBACK_DAYS
    APPLY_LOOKBACK_TO_MANUAL_PULLS = False
 
    def __init__(self, connection):
        self._error_handler = NordeaBusinessErrorHandler(PROVIDER_NAME)
        self._auth = NordeaAuth(connection, error_handler=self._error_handler)
        self._http = NordeaHTTPClient(self._auth, self._auth.base_url, error_handler=self._error_handler)
        self._connection = connection
        
    def close(self) -> None:
        self._http.close()
        self._auth.close()
 
    def __enter__(self) -> "NordeaBusinessService":
        return self
 
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def max_transaction_pages(self) -> int | None:
        return None

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    def _should_include_transaction(self, dto: TransactionDTO) -> bool:
        """Only import transactions that have reached Nordea's final state."""
        return dto.status in NordeaTransactionStatus.FINAL_STATUSES
