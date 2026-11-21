import logging
import requests

from ..base_auth import BaseAuth
from ...constants.http import (
    CONTENT_TYPE_FORM, 
    CONTENT_TYPE_JSON, 
    HEADER_CONTENT_TYPE,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    BEARER_PREFIX,
    CONNECT_TIMEOUT_SECONDS, 
    READ_TIMEOUT_SECONDS,
    )
from .constants.op_auth_config import BACKEND_SANDBOX, TOKEN_DEFAULT_EXPIRY_SECONDS
from .constants.op_api import (
    SANDBOX_TOKEN_URL, 
    PROD_TOKEN_URL,
    SANDBOX_BASE,
    PROD_BASE,
    )
from ...error_handling.error_types import BankingError
from ...error_handling.http_error_mapping import check_response_for_status, transport_errors
from ...error_handling.rest_error_types import BankingTokenError
from .op_cert_cache import get_or_create_cert_files


_logger = logging.getLogger(__name__)

class OPAuth(BaseAuth):
    def __init__(self, env, client_id: str, client_secret: str, cert_pem: str, key_pem: str, connection=None, error_handler=None):
        super().__init__(connection)

        self.env = env
        self._client_id = client_id
        self._client_secret = client_secret
        self._cert_pem = cert_pem
        self._key_pem = key_pem
        self._error_handler = error_handler
        
        sandbox = connection.api_backend == BACKEND_SANDBOX.key
        self._token_url = SANDBOX_TOKEN_URL if sandbox else PROD_TOKEN_URL
        self.base_url = SANDBOX_BASE if sandbox else PROD_BASE
        
    def get_cert_paths(self) -> tuple[str, str]:
        """Returns cert/key paths, using cache where possible."""
        return get_or_create_cert_files(self._cache_key, self._cert_pem, self._key_pem)

    def get_auth_headers(self) -> dict:
        return self._build_auth_headers(self.get_valid_token())

    def _fetch_or_refresh_access_token(self) -> str:
        """Fetches a new OAuth2 access token using client credentials + mTLS."""
        cert = self.get_cert_paths()
        try:
            _logger.info("Fetching new OP access token.")
            # TODO move to http
            with transport_errors():
                resp = requests.post(
                    self._token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={HEADER_CONTENT_TYPE: CONTENT_TYPE_FORM},
                    cert=cert,
                    timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                )
            _logger.debug(
                "OP Corporate: token response %s for connection %s",
                resp.status_code, self.connection.id,
            )
            check_response_for_status(resp, BankingTokenError)

        except BankingError as e:
            self._error_handler.handle(e)

        data = resp.json()
        expires_in = data.get("expires_in", TOKEN_DEFAULT_EXPIRY_SECONDS)
        token = data["access_token"]

        self._cache_token(token, expires_in)

        _logger.info(
            "OP Corporate: new access token fetched for connection %s, expires in %ds",
            self.connection.id, expires_in,
        )
        return token
    
    # headers
    def _build_auth_headers(self, token: str) -> dict:
        return {
            HEADER_AUTHORIZATION: f"{BEARER_PREFIX}{token}",
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
        }
