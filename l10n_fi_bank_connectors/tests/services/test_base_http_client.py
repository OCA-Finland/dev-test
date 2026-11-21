import requests.exceptions

from unittest.mock import MagicMock

from odoo.tests.common import BaseCase

from ...services.base_http_client import BaseHTTPClient
from ...services.constants.http import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS
from ...services.error_handling.error_types import BankingAPIError, BankingTransportError

TEST_URL = "https://example.invalid"


class TestBaseHTTPClient(BaseCase):
    def setUp(self):
        super().setUp()
        self.error_handler = MagicMock()
        self.client = BaseHTTPClient(self.error_handler)
        self.client._session = MagicMock()

    def _failed_response(self, status_code=503):
        response = MagicMock(ok=False, status_code=status_code, text="unavailable")
        response.json.side_effect = ValueError
        return response

    def test_send_returns_raw_response(self):
        response = MagicMock(ok=True)
        self.client._session.request.return_value = response
        self.assertIs(self.client.send("get", TEST_URL), response)

    def test_send_passes_headers_and_timeout_tuple(self):
        self.client._session.request.return_value = MagicMock(ok=True)

        self.client.send("post", TEST_URL, headers={"X-Test": "1"}, data=b"body")

        self.client._session.request.assert_called_once_with(
            "post",
            TEST_URL,
            headers={"X-Test": "1"},
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            data=b"body",
        )

    def test_network_failure_is_a_transport_error(self):
        self.client._session.request.side_effect = requests.exceptions.ConnectionError("unreachable")

        with self.assertRaises(BankingTransportError):
            self.client.send("get", TEST_URL)
        self.error_handler.handle.assert_called_once()

    def test_ssl_failure_keeps_ssl_error_as_cause(self):
        self.client._session.request.side_effect = requests.exceptions.SSLError("bad cert")

        with self.assertRaises(BankingTransportError) as context:
            self.client.send("get", TEST_URL)
        self.assertIsInstance(context.exception.__cause__, requests.exceptions.SSLError)

    def test_http_error_is_an_api_error(self):
        self.client._session.request.return_value = self._failed_response(503)

        with self.assertRaises(BankingAPIError) as context:
            self.client.send("get", TEST_URL)
        self.assertEqual(context.exception.status_code, 503)
        self.error_handler.handle.assert_called_once()

    def test_client_cert_is_set_on_session(self):
        client = BaseHTTPClient(self.error_handler, client_cert=("cert", "key"))
        self.assertEqual(client._session.cert, ("cert", "key"))
