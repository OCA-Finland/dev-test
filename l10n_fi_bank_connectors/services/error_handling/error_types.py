"""Errors used by all providers."""

class BankingError(Exception):
    """Base for every failed call."""

class BankingTransportError(BankingError):
    """Covers timeout, connection failure and other network failures."""

class BankingAPIError(BankingError):
    """Raised for non-2xx HTTP responses."""
    def __init__(self, status_code: int, message: str, body: dict = None):
        self.status_code = status_code
        self.body = body or {}
        self.message = message
        super().__init__(message)

class AccountRefreshNotSupported(Exception):
    """Raised by services that have no remote account info to refresh. Callers will skip the connection."""