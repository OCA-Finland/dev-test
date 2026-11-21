from odoo.exceptions import UserError
from odoo.tests.common import BaseCase

from ...services.error_handling.error_types import (
    BankingError,
    BankingTransportError,
)
from ...services.error_handling.op_error_handler import OPErrorHandler
from ...services.error_handling.soap_error_types import (
    BankingProtocolError,
    BankingResponseCodeError,
)


class TestErrorHandlerBaseDispatch(BaseCase):
    def setUp(self):
        super().setUp()
        self.handler = OPErrorHandler("Test Provider")

    def _translate(self, exc):
        with self.assertRaises(UserError) as context:
            self.handler.handle(exc)
        return str(context.exception)

    def test_protocol_error_is_not_reported_as_connection_failure(self):
        message = self._translate(BankingProtocolError("No SOAP Body"))
        self.assertIn("unexpected response", message)
        self.assertNotIn("could not connect", message)

    def test_application_error_uses_default_message_with_code(self):
        message = self._translate(BankingResponseCodeError("31", "Duplicate MsgId"))
        self.assertIn("rejected the request", message)
        self.assertIn("31", message)

    def test_unknown_banking_error_becomes_user_error(self):
        class CustomBankingError(BankingError):
            pass
        self.assertIn("unexpected error", self._translate(CustomBankingError("boom")))

    def test_protocol_error_is_not_a_transport_error(self):
        self.assertNotIsInstance(BankingProtocolError("x"), BankingTransportError)

    def test_find_cause_stops_on_cycles(self):
        first = BankingError("a")
        second = BankingError("b")
        first.__cause__ = second
        second.__cause__ = first

        self.assertIsNone(self.handler._find_cause(first, ValueError))
        self.assertIs(self.handler._find_cause(first, BankingError), first)