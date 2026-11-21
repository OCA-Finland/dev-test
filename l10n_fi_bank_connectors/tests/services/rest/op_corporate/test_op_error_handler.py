import requests.exceptions

from odoo.exceptions import UserError
from odoo.tests.common import BaseCase

from .....services.error_handling.error_types import (
    BankingAPIError,
    BankingError,
    BankingTransportError,
)
from .....services.error_handling.op_error_handler import OPErrorHandler
from .....services.error_handling.rest_error_types import BankingTokenError


class TestOPErrorHandler(BaseCase):
    def setUp(self):
        super().setUp()
        self.handler = OPErrorHandler("Test Provider")

    def test_mapped_status_uses_mapped_message(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingAPIError(403, "HTTP 403"))
        self.assertEqual(str(context.exception), "Test Provider: not authorized.")

    def test_server_error_warns_that_payment_status_is_unknown(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingAPIError(500, "HTTP 500"))
        self.assertIn("status is unknown", str(context.exception))

    def test_body_detail_is_appended_to_mapped_message(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingAPIError(400, "HTTP 400", {"message": "bad field"}))
        self.assertIn("bad request", str(context.exception))
        self.assertTrue(str(context.exception).endswith("(bad field)"))

    def test_unmapped_status_uses_generic_message(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingAPIError(418, "HTTP 418"))
        self.assertIn("unexpected error", str(context.exception))

    def test_tls_transport_error_has_tls_message(self):
        error = BankingTransportError("TLS failed")
        error.__cause__ = requests.exceptions.SSLError("certificate verify failed")
        with self.assertRaises(UserError) as context:
            self.handler.handle(error)
        self.assertIn("TLS error", str(context.exception))

    def test_other_transport_error_has_generic_message(self):
        error = BankingTransportError("timed out")
        error.__cause__ = requests.exceptions.ConnectTimeout("timed out")
        with self.assertRaises(UserError) as context:
            self.handler.handle(error)
        self.assertIn("could not connect to the bank", str(context.exception))

    def test_is_auth_error_true_for_token_error_with_auth_code(self):
        self.assertTrue(self.handler.is_auth_error(BankingTokenError(401, "HTTP 401")))

    def test_is_auth_error_true_when_token_error_is_in_cause_chain(self):
        outer = BankingError("wrapped")
        outer.__cause__ = BankingTokenError(401, "HTTP 401")
        self.assertTrue(self.handler.is_auth_error(outer))

    def test_is_auth_error_false_for_token_error_with_other_code(self):
        self.assertFalse(self.handler.is_auth_error(BankingTokenError(400, "HTTP 400")))

    def test_is_auth_error_false_for_plain_api_error(self):
        self.assertFalse(self.handler.is_auth_error(BankingAPIError(401, "HTTP 401")))

    def test_non_dict_body_adds_no_detail(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingAPIError(400, "HTTP 400", ["unexpected", "body"]))
        self.assertNotIn("(", str(context.exception))
        self.assertNotIn("unexpected", str(context.exception))

    def test_nested_values_are_not_rendered_as_python_repr(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingAPIError(400, "HTTP 400", {"errors": ["a", "b"]}))
        self.assertNotIn("['a', 'b']", str(context.exception))

    def test_raw_http_text_is_logged(self):
        with self.assertLogs("odoo", level="WARNING") as logs:
            with self.assertRaises(UserError):
                self.handler.handle(BankingAPIError(400, "HTTP 400: raw bank text"))
        self.assertIn("raw bank text", "\n".join(logs.output))

    def test_tls_error_deeper_in_cause_chain_is_detected(self):
        middle = RuntimeError("wrapped")
        middle.__cause__ = requests.exceptions.SSLError("certificate verify failed")
        error = BankingTransportError("TLS failed")
        error.__cause__ = middle

        with self.assertRaises(UserError) as context:
            self.handler.handle(error)
        self.assertIn("TLS error", str(context.exception))

    def test_tls_error_cause_is_logged(self):
        error = BankingTransportError("TLS failed")
        error.__cause__ = requests.exceptions.SSLError("certificate verify failed")

        with self.assertLogs("odoo", level="ERROR") as logs:
            with self.assertRaises(UserError):
                self.handler.handle(error)
        self.assertIn("certificate verify failed", "\n".join(logs.output))