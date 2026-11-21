import json
import logging

from abc import ABC, abstractmethod

from odoo.exceptions import UserError

from .error_types import BankingAPIError, BankingError, BankingTransportError
from .rest_error_types import BankingTokenError
from .soap_error_types import BankingProtocolError, BankingResponseCodeError

_logger = logging.getLogger(__name__)


def _find_in_cause_chain(exc: BaseException | None, exc_type: type) -> BaseException | None:
    """Return the first exception of exc_type in exc's __cause__ chain (exc included)."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, exc_type):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__
    return None


class ErrorHandler(ABC):
    """Base class for error handling."""

    def __init__(self, provider_name: str):
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def handle(self, exc: BankingError, **context) -> None:
        """Translate a BankingError into a UserError. Always raises."""
        if isinstance(exc, BankingProtocolError):
            self._handle_protocol_error(exc)
        elif isinstance(exc, BankingResponseCodeError):
            self._handle_response_code_error(exc)
        elif isinstance(exc, BankingTransportError):
            self._handle_transport_error(exc)
        elif isinstance(exc, BankingAPIError):
            self._handle_api_error(exc, **context)
        else:
            self._handle_unknown_error(exc)
        raise exc

    def _handle_transport_error(self, exc: BankingTransportError) -> None:
        """No response was obtained from the bank: log the cause and raise a UserError."""
        _logger.error("%s: transport error: %s", self._provider_name, exc.__cause__ or exc)
        raise UserError(
            f"{self._provider_name}: could not connect to the bank. Please try again later or contact support."
        ) from exc

    def _handle_protocol_error(self, exc: BankingProtocolError) -> None:
        """A response was received, but its payload was malformed or unexpected."""
        _logger.error("%s: protocol error: %s", self._provider_name, exc)
        raise UserError(
            f"{self._provider_name}: the bank returned an unexpected response. "
            "Please try again later or contact support."
        ) from exc

    def _handle_response_code_error(self, exc: BankingResponseCodeError) -> None:
        """The bank rejected the request at application level."""
        _logger.warning(
            "%s: application error, response code %s: %s",
            self._provider_name, exc.response_code, exc.message,
        )
        raise UserError(
            f"{self._provider_name}: the bank rejected the request (response code {exc.response_code})."
        ) from exc

    def _handle_unknown_error(self, exc: BankingError) -> None:
        """A BankingError subclass nobody handles explicitly."""
        _logger.error("%s: unhandled %s: %s", self._provider_name, type(exc).__name__, exc)
        raise UserError(
            f"{self._provider_name}: an unexpected error occurred. Please try again or contact support."
        ) from exc

    @staticmethod
    def _find_cause(exc: BaseException | None, exc_type: type) -> BaseException | None:
        """Return the first exception of exc_type in exc's __cause__ chain (exc itself included)."""
        return _find_in_cause_chain(exc, exc_type)

    @abstractmethod
    def _handle_api_error(self, exc: BankingAPIError, **context) -> None:
        """A response was received: translate it into a UserError. Must raise."""

    def is_auth_error(self, exc: BaseException) -> bool:
        """True if a failed token request with an auth status code is in exc's cause chain."""
        token_error = self._find_cause(exc, BankingTokenError)
        return token_error is not None and token_error.status_code in self._auth_error_codes

    def is_auth_error(self, exc: BaseException) -> bool:
        """True if exc means the stored credentials or consent are no longer valid.

        Default: never. Certificate-based providers (SOAP) need credential repair,
        not consent-style cron pausing. Providers with token requests override this.
        """
        return False


class RestErrorHandler(ErrorHandler):
    """Base class for handlers of REST/JSON providers."""

    @property
    @abstractmethod
    def _error_map(self) -> dict[int, str]:
        """Map HTTP status code -> message template."""

    # HTTP status codes of a failed token request that count as an auth failure
    _auth_error_codes: frozenset[int] = frozenset()

    def is_auth_error(self, exc: BaseException) -> bool:
        """True if a failed token request with an auth status code is in exc's cause chain."""
        token_error = self._find_cause(exc, BankingTokenError)
        return token_error is not None and token_error.status_code in self._auth_error_codes

    def _handle_api_error(self, exc: BankingAPIError, **context) -> None:
        ctx = {"provider": self._provider_name, **context}
        template = self._error_map.get(exc.status_code)
        detail = self._extract_detail(exc.body)

        if template:
            msg = template.format(**ctx)
            if detail:
                msg = f"{msg} ({detail})"
            _logger.warning("%s: %s", self._provider_name, exc.message)
            raise UserError(msg) from exc

        _logger.warning(
            "%s: unmapped HTTP %s error — %s",
            self._provider_name, exc.status_code, detail or exc.message,
        )
        _logger.warning("%s: unmapped %s", self._provider_name, exc.message)
        raise UserError(
            f"{self._provider_name}: an unexpected error occurred. Please try again or contact support."
        ) from exc


    def _extract_detail(self, body: dict) -> str:
        """Return a user-safe detail string from the error body, or "" if there is none."""
        if not body or not isinstance(body, dict):
            return ""
        for key in ("message", "detail", "error", "errors"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        return json.dumps(body, ensure_ascii=False)