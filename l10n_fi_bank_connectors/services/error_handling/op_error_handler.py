import logging

import requests.exceptions

from odoo import _
from odoo.exceptions import UserError

from .base_error_handler import RestErrorHandler
from .error_types import BankingTransportError

_logger = logging.getLogger(__name__)

AUTH_ERROR_CODES = {401}


class OPErrorHandler(RestErrorHandler):
    """Error handler for OP Corporate API."""

    _auth_error_codes = frozenset(AUTH_ERROR_CODES)

    @property
    def _error_map(self) -> dict[int, str]:
        return {
            400: "{provider}: bad request. Check your configuration.",
            401: "{provider}: invalid credentials. Check that your certificate, "
                 "Client ID and Client Secret are correct.",
            403: "{provider}: not authorized.",
            500: "{provider}: server error. "
                 "If this was a payment, the status is unknown — check the payment log.",
            503: "{provider}: service temporarily unavailable. Please try again later.",
            504: "{provider}: gateway timeout.",
        }

    def _handle_transport_error(self, exc: BankingTransportError) -> None:
        """Keep the TLS-specific message, everything else uses the base message."""
        ssl_error = self._find_cause(exc, requests.exceptions.SSLError)
        if ssl_error is not None:
            _logger.error("%s: TLS error: %s", self._provider_name, ssl_error)
            raise UserError(
                _("%s: TLS error. Check that your certificate and private key are valid, "
                  "matching, and in PEM format, and that the certificate was "
                  "registered in OP API Admin.") % self._provider_name
            ) from exc
        super()._handle_transport_error(exc)