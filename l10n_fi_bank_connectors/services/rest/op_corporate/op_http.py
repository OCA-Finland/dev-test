import logging
import requests

from odoo import _
from odoo.exceptions import UserError

from ...base_http_client import BaseHTTPClient
from ...constants.http import CONTENT_TYPE_JSON, HEADER_CONTENT_TYPE
from .constants.op_api import HEADER_OP_SIGNATURE, PAYMENT_PATH

_logger = logging.getLogger(__name__)

"""
The bytes variants exist so the exact bank response body can be saved in the payment log (online_bank_payment_log) as payload.

"""

class OPHTTPClient(BaseHTTPClient):
    def _get(self, path: str, params: dict = None) -> dict:
        return self._get_with_bytes(path, params)[0]

    def _get_with_bytes(self, path: str, params: dict = None) -> tuple[dict, bytes]:
        return self._request_with_bytes('get', f"{self._base}{path}", params=params)

    def _post_payment(self, payload_str: str, signature: str) -> dict:
        return self._post_payment_with_bytes(payload_str, signature)[0]

    def _post_payment_with_bytes(self, payload_str: str, signature: str) -> tuple[dict, bytes]:
        return self._request_with_bytes(
            'post',
            f"{self._base}{PAYMENT_PATH}",
            extra_headers={HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON, HEADER_OP_SIGNATURE: signature},
            data=payload_str,
        )

    def _request_with_bytes(self, method, url, extra_headers=None, **kwargs) -> tuple[dict, bytes]:
        headers = self._auth.get_auth_headers()
        if extra_headers:
            headers.update(extra_headers)

        response = self.send(method, url, headers=headers, **kwargs)
        try:
            data = response.json() if response.content else {}
        except requests.exceptions.JSONDecodeError as e:
            _logger.error(
                "OP: failed to decode JSON response from %s %s: %s",
                method.upper(), url, e,
            )
            raise UserError(
                _("%s: received an invalid response. Please try again or contact support.")
                % self._error_handler.provider_name
            ) from e
        return data, response.content