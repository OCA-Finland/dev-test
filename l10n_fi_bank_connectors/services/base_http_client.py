import requests

from .constants.http import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS
from .error_handling.error_types import BankingAPIError, BankingError
from .error_handling.http_error_mapping import check_response_for_status, transport_errors


class BaseHTTPClient:
    """
    Shared HTTP plumbing: session, timeout, optional TLS cert, send, and error handling. 
    URL building, headers, body building and JSON/XML decoding delegated to subclasses.
    """

    def __init__(self, error_handler, client_cert: tuple[str, str] | None = None):
        self._error_handler = error_handler
        self._timeout = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
        self._session = requests.Session()
        if client_cert:
            self._session.cert = client_cert

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "BaseHTTPClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def send(self, method: str, url: str, headers: dict | None = None, error_cls: type[BankingAPIError] | None = None, **kwargs, ) -> requests.Response:
        """Send a request and return the raw response. Errors go through the error handler."""
        try:
            with transport_errors():
                response = self._session.request(method, url, headers=headers, timeout=self._timeout, **kwargs)
            self._check_response(response, error_cls)
            return response
        except BankingError as exc:
            self._error_handler.handle(exc)
            raise

    def _check_response(self, response: requests.Response, error_cls: type[BankingAPIError] | None = None) -> None:
        """Hook for subclasses. Default: map non-2xx to BankingAPIError."""
        check_response_for_status(response, error_cls)