import logging
import requests.exceptions

from odoo import _
from odoo.exceptions import UserError

from .base_error_handler import ErrorHandler
from .error_types import BankingAPIError, BankingTransportError
from .soap_error_types import BankingProtocolError, BankingResponseCodeError

_logger = logging.getLogger(__name__)


# see Appendix A in: https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
_APPLICATION_ERRORS = {
    "02": "SOAP signature verification failed.",
    "03": "SOAP signature verification failed.",
    "04": "SOAP signature verification failed.",
    "07": "The sender ID is not registered with Nordea.",
    "08": "The sender ID is locked by Nordea.",
    "12": "Nordea rejected the request because its XML schema is invalid.",
    "14": "The customer ID is locked.",
    "15": "The customer ID is outdated.",
    "18": "The content digital signature is invalid.",
    "19": "The signing certificate is invalid, expired, or revoked.",
    "20": "The content does not match the declared file type.",
    "21": "Nordea could not decompress the submitted content.",
    "22": "Nordea could not decrypt the submitted content.",
    "23": "Nordea could not process the submitted content.",
    "24": "The requested content was not found.",
    "25": "The signature algorithm is not supported.",
    "26": "Nordea reported a technical error.",
    "29": "Nordea rejected an invalid request parameter.",
    "30": "Authentication failed: the sender or signer ID is unknown.",
    "31": "Nordea rejected a duplicate message ID.",
    "33": "Nordea reported an error in the customer information.",
    "35": "The signer is not authorized to submit this file type.",
    "36": "Nordea reported a technical error. Contact the bank helpdesk.",
    "37": "Nordea could not process the ApplicationRequest.",
    "SOAP_FAULT": "Nordea returned a SOAP fault.",
}


class NordeaCAErrorHandler(ErrorHandler):
    """Error handler for Nordea Corporate Access Web Service."""

    @property
    def _error_map(self) -> dict[int, str]:
        return {
            400: "{provider}: Nordea rejected the request.",
            401: "{provider}: Nordea did not authorize the request.",
            403: "{provider}: the request is not authorized.",
            404: "{provider}: the endpoint was not found.",
            500: "{provider}: Nordea returned a server error.",
            502: "{provider}: the Nordea endpoint is unavailable.",
            503: "{provider}: the Nordea service is temporarily unavailable.",
            504: "{provider}: the Nordea gateway timed out.",
        }

    def is_auth_error(self, _exc: BaseException) -> bool:
        """CA certificate failures require credential repair, not consent-style cron pausing."""
        return False

    def _handle_response_code_error(self, exc: BankingResponseCodeError) -> None:
        description = _APPLICATION_ERRORS.get(exc.response_code)
        if description is None:
            description = "Nordea returned an unrecognized application error."
        detail = f" ({exc.message})" if exc.message else ""
        _logger.warning(
            "%s: Nordea response code %s — %s%s",
            self._provider_name,
            exc.response_code,
            description,
            detail,
        )
        raise UserError(
            _("%s: %s%s (response code %s).")
            % (self._provider_name, description, detail, exc.response_code)
        ) from exc

    def _handle_api_error(self, exc: BankingAPIError, **_context) -> None:
        template = self._error_map.get(exc.status_code)
        if template is None:
            _logger.warning(
                "%s: unmapped HTTP %s error from SOAP endpoint",
                self._provider_name,
                exc.status_code,
            )
            raise UserError(
                _("%s: an unexpected SOAP endpoint error occurred. Please try again later.")
                % self._provider_name
            ) from exc

        _logger.warning(
            "%s: HTTP %s error from SOAP endpoint",
            self._provider_name,
            exc.status_code,
        )
        raise UserError(template.format(provider=self._provider_name)) from exc

    def _handle_transport_error(self, exc: BankingTransportError) -> None:
        cause = exc.__cause__
        seen = set()
        while cause is not None and id(cause) not in seen:
            if isinstance(cause, requests.exceptions.SSLError):
                _logger.error("%s: TLS client certificate failure: %s", self._provider_name, cause)
                raise UserError(
                    _("%s: TLS authentication failed. Check that the client certificate "
                      "and private key match and that the certificate is valid, not expired, "
                      "and not revoked.") % self._provider_name
                ) from exc
            seen.add(id(cause))
            cause = cause.__cause__
        super()._handle_transport_error(exc)

    def _handle_protocol_error(self, exc: BankingProtocolError) -> None:
            _logger.error("%s: malformed SOAP response: %s", self._provider_name, exc)
            raise UserError(
                _("%s: Nordea returned a malformed SOAP response. Please try again later "
                  "or contact support.") % self._provider_name
            ) from exc

    def is_auth_error(self, _exc: BaseException) -> bool:
        """CA certificate failures require credential repair, not consent-style cron pausing."""
        return False
