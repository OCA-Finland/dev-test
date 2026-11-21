from .constants.op_api import (
    TRANSACTION_HISTORY_LIMIT_DAYS as OP_TRANSACTION_HISTORY_LIMIT_DAYS,
    TRANSACTION_LOOKBACK_DAYS as OP_TRANSACTION_LOOKBACK_DAYS, 
    TRANSACTION_MAX_PAGES,
)
from .constants.op_auth_config import PROVIDER_NAME, BACKEND_SANDBOX
from ...error_handling import OPErrorHandler
from ..http_paginated_transactions import HTTPPaginatedTransactions
from .op_ais import OPAIS
from .op_auth import OPAuth
from .op_http import OPHTTPClient
from .op_mappers import OPMappers
from .op_pis import OPPIS


class OPCorporateService(OPHTTPClient, OPMappers, OPAIS, OPPIS, HTTPPaginatedTransactions):
    TRANSACTION_HISTORY_LIMIT_DAYS = OP_TRANSACTION_HISTORY_LIMIT_DAYS
    TRANSACTION_LOOKBACK_DAYS = OP_TRANSACTION_LOOKBACK_DAYS
    
    def __init__(self, env, client_id, client_secret, cert_pem, key_pem,
                connection=None, signing_key_pem=None, signing_kid=None):
        self._error_handler = OPErrorHandler(PROVIDER_NAME)
        
        self._auth = OPAuth(
            env, client_id, client_secret, cert_pem, key_pem,
            connection=connection,
            error_handler=self._error_handler,
        )
        self._base = self._auth.base_url
        self._signing_key_pem = signing_key_pem
        self._signing_kid = signing_kid
        
        super().__init__(
            self._error_handler,
            client_cert=self._auth.get_cert_paths(),
        )

    @property
    def max_transaction_pages(self) -> int | None:
        connection = self._auth.connection
        if connection and connection.api_backend == BACKEND_SANDBOX.key:
            return TRANSACTION_MAX_PAGES
        return None

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME
