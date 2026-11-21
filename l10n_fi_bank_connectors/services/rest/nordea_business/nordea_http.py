import json
import logging
import requests

from typing import Protocol

from odoo import _
from odoo.exceptions import UserError

from ...base_http_client import BaseHTTPClient
from ...constants.http import ENCODING_UTF8, HEADER_LOCATION, HTTP_SCHEME, HTTPS_SCHEME
from ...error_handling.rest_error_types import BankingTokenError

_logger = logging.getLogger(__name__)


class AuthProvider(Protocol):
    """Interface for providing authentication headers to NordeaHTTPClient."""
    def get_auth_headers(self, method: str, path: str, body_bytes: bytes = None) -> dict: ...
    def get_pre_auth_headers(self, method: str, path: str, body_bytes: bytes = None) -> dict: ...
    def get_sandbox_authorizer_header(self) -> dict: ...


class NordeaHTTPClient(BaseHTTPClient):
    """Handle HTTP requests for Nordea Business API."""
    def __init__(self, auth: AuthProvider, base_url: str, error_handler=None):
        super().__init__(error_handler)
        self._auth = auth
        self._base = base_url

    def _build_url(self, path: str) -> str:
        """Return path unchanged if it is an absolute URL, otherwise prefix it with the base URL."""
        if path.startswith((HTTP_SCHEME, HTTPS_SCHEME)):
            return path
        return f"{self._base}{path}"

    def post_authorize(self, path: str, body: dict) -> str:
        """
        POST to the /authorize endpoint. Returns the redirect Location URL.
        Nordea responds with 302/303-> capture location.
        """
        url = self._build_url(path)
        body_bytes = json.dumps(body, separators=(',', ':')).encode(ENCODING_UTF8)
        headers = {
            **self._auth.get_pre_auth_headers('post', path, body_bytes),
            **self._auth.get_sandbox_authorizer_header(),
        }
        response = self.send("post", url, headers=headers, data=body_bytes, allow_redirects=False)

        if response.status_code not in (302, 303):
            raise UserError(_(
                "Nordea: authorization request returned unexpected status %s. "
                "Expected a redirect." % response.status_code
            ))

        location = response.headers.get(HEADER_LOCATION)
        if not location:
            raise UserError(_(
                "Nordea: authorization succeeded but no redirect URL was returned."
            ))
        return location

    def post_form(self, url: str, encoded_body: str, headers: dict) -> requests.Response:
        """POST url-encoded form data. Used for token requests."""
        return self.send("post", url, headers=headers, data=encoded_body, error_cls=BankingTokenError)

    def get(self, path: str, params: dict = None) -> dict:
        """GET request to the Nordea Business API."""
        return self.get_with_bytes(path, params)[0]

    def get_with_bytes(self, path: str, params: dict = None) -> tuple[dict, bytes]:
        """GET request returning the parsed JSON and the raw response body."""
        return self._request_with_bytes("get", path, params=params)

    def put(self, path: str, body: dict) -> dict:
        """PUT request to the Nordea Business API."""
        return self.put_with_bytes(path, body)[0]

    def put_with_bytes(self, path: str, body: dict) -> tuple[dict, bytes]:
        """PUT request returning the parsed JSON and the raw response body."""
        return self._request_with_bytes("put", path, body=body)

    def _request_with_bytes(self, method: str, path: str, params: dict = None, body: dict = None) -> tuple[dict, bytes]:
        """HTTP request to the Nordea Business API using the specified method."""
        url = self._build_url(path)
        body_bytes = json.dumps(body, separators=(',', ':')).encode(ENCODING_UTF8) if body else None
        headers = {
            **self._auth.get_auth_headers(method, path, body_bytes),
            **self._auth.get_sandbox_authorizer_header(),
        }
        response = self.send(method, url, headers=headers, params=params, data=body_bytes)
        try:
            data = response.json() if response.content else {}
        except requests.exceptions.JSONDecodeError as e:
            _logger.error(
                "Nordea: failed to decode JSON response from %s %s: %s",
                method.upper(), url, e,
            )
            raise UserError(
                _("%s: received an invalid response. Please try again or contact support.")
                % self._error_handler.provider_name
            ) from e
        return data, response.content