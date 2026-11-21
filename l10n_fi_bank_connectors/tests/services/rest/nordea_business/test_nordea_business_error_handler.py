from odoo.exceptions import UserError
from odoo.tests.common import BaseCase

import requests.exceptions

from .....services.error_handling.error_types import (
    BankingAPIError,
    BankingError,
    BankingTransportError,
)
from .....services.error_handling.rest_error_types import BankingTokenError
from .....services.error_handling.nordea_business_error_handler import NordeaBusinessErrorHandler


class TestNordeaBusinessErrorHandler(BaseCase):
    def setUp(self):
        super().setUp()
        self.handler = NordeaBusinessErrorHandler("Test Provider")

    def _translate(self, exc):
        with self.assertRaises(UserError) as context:
            self.handler.handle(exc)
        return str(context.exception)

    def test_mapped_status_uses_mapped_message(self):
        self.assertEqual(
            self._translate(BankingAPIError(404, "HTTP 404")),
            "Test Provider: resource not found.",
        )

    def test_unmapped_status_uses_generic_message(self):
        self.assertIn("unexpected error", self._translate(BankingAPIError(500, "HTTP 500")))

    def test_failure_description_is_appended_to_mapped_message(self):
        body = {"error": {"failures": [{"description": "Invalid IBAN"}]}}
        message = self._translate(BankingAPIError(400, "HTTP 400", body))
        self.assertIn("bad request", message)
        self.assertTrue(message.endswith("(Invalid IBAN)"))

    def test_failure_code_is_used_when_description_is_missing(self):
        body = {"error": {"failures": [{"code": "E42"}]}}
        self.assertTrue(self._translate(BankingAPIError(400, "HTTP 400", body)).endswith("(E42)"))

    def test_multiple_failures_are_joined_and_invalid_entries_skipped(self):
        body = {"error": {"failures": [{"description": "Invalid IBAN"}, "junk", {}, {"code": "E42"}]}}
        message = self._translate(BankingAPIError(400, "HTTP 400", body))
        self.assertTrue(message.endswith("(Invalid IBAN; E42)"))

    def test_no_detail_when_failures_are_empty(self):
        message = self._translate(BankingAPIError(400, "HTTP 400", {"error": {"failures": []}}))
        self.assertNotIn("(", message)

    def test_no_detail_when_error_is_not_a_dict(self):
        message = self._translate(BankingAPIError(400, "HTTP 400", {"error": "boom"}))
        self.assertNotIn("(", message)

    def test_transport_error_has_generic_message(self):
        error = BankingTransportError("timed out")
        error.__cause__ = requests.exceptions.ConnectTimeout("timed out")
        self.assertIn("could not connect to the bank", self._translate(error))

    def test_is_auth_error_true_for_token_error_with_auth_codes(self):
        for status_code in (400, 401, 403):
            with self.subTest(status_code=status_code):
                self.assertTrue(self.handler.is_auth_error(BankingTokenError(status_code, "HTTP")))

    def test_is_auth_error_true_when_token_error_is_in_cause_chain(self):
        outer = BankingError("wrapped")
        outer.__cause__ = BankingTokenError(401, "HTTP 401")
        self.assertTrue(self.handler.is_auth_error(outer))

    def test_is_auth_error_false_for_token_error_with_other_code(self):
        self.assertFalse(self.handler.is_auth_error(BankingTokenError(404, "HTTP 404")))

    def test_is_auth_error_false_for_plain_api_error(self):
        self.assertFalse(self.handler.is_auth_error(BankingAPIError(401, "HTTP 401")))

    def test_non_dict_body_adds_no_detail(self):
        message = self._translate(BankingAPIError(401, "HTTP 401", ["unexpected", "body"]))
        self.assertNotIn("(", message)
        self.assertNotIn("unexpected", message)