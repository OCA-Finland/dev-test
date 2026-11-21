import requests

from contextlib import contextmanager
from .error_types import BankingAPIError, BankingTransportError

"""Helper methods for mapping response to BankingAPIError"""

def check_response_for_status(response: requests.Response, error_cls: type[BankingAPIError] | None = None) -> None:
    """Maps a non-2xx response into BankingAPIError."""
    if response.ok:
        return

    body = {}
    text = response.text or ""
    try:
        body = response.json()
    except Exception:
        pass

    message = f"HTTP {response.status_code}"
    if text:
        message += f": {text}"
    raise (error_cls or BankingAPIError)(response.status_code, message, body)


@contextmanager
def transport_errors():
    """Convert any requests exception raised inside the block into BankingTransportError."""
    try:
        yield
    except requests.exceptions.RequestException as e:
        raise BankingTransportError(str(e)) from e