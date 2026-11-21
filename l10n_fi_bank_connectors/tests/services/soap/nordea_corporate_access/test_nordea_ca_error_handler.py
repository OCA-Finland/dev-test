import base64
import requests.exceptions

from lxml import etree
from unittest.mock import MagicMock

from odoo.exceptions import UserError
from odoo.tests.common import BaseCase

from .....services.error_handling.error_types import BankingAPIError, BankingTransportError
from .....services.error_handling.nordea_ca_error_handler import NordeaCAErrorHandler
from .....services.error_handling.rest_error_types import BankingTokenError
from .....services.error_handling.soap_error_types import BankingProtocolError, BankingResponseCodeError
from .....services.soap.nordea_corporate_access.constants.namespaces import NS_SOAPENV, XMLDATA_NAMESPACE
from .....services.soap.nordea_corporate_access.nordea_ca_ais import NordeaCorporateAccessAIS
from .....services.soap.nordea_corporate_access.nordea_ca_request_executor import NordeaCARequestExecutor
from .....services.soap.nordea_corporate_access.nordea_ca_ws_client import NordeaWSClient


class TestNordeaCAErrorHandler(BaseCase):
    def setUp(self):
        super().setUp()
        self.handler = NordeaCAErrorHandler("Nordea Corporate Access")

    def test_application_errors_are_translated(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingResponseCodeError("31", "Duplicate MsgId"))
        self.assertIn("duplicate message ID", str(context.exception))
        self.assertIn("31", str(context.exception))

    def test_secure_envelope_errors_have_specific_messages(self):
        expected_messages = {
            "02": "signature verification failed",
            "07": "sender ID is not registered",
            "12": "XML schema is invalid",
            "19": "expired, or revoked",
            "30": "sender or signer ID is unknown",
        }
        for code, message in expected_messages.items():
            with self.subTest(response_code=code):
                with self.assertRaises(UserError) as context:
                    self.handler.handle(BankingResponseCodeError(code, "Bank response"))
                self.assertIn(message, str(context.exception))

    def test_certificate_and_sender_failures_do_not_count_as_consent_auth_errors(self):
        self.assertFalse(self.handler.is_auth_error(BankingResponseCodeError("19", "Expired")))
        self.assertFalse(self.handler.is_auth_error(BankingAPIError(401, "Unauthorized")))
        self.assertFalse(self.handler.is_auth_error(BankingResponseCodeError("30", "Unknown sender")))

    def test_http_errors_are_translated(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingAPIError(503, "HTTP 503"))
        self.assertIn("temporarily unavailable", str(context.exception))

    def test_tls_transport_error_explains_certificate_repair(self):
        cause = requests.exceptions.SSLError("certificate verify failed")
        error = BankingTransportError("TLS connection failed")
        error.__cause__ = cause

        with self.assertRaises(UserError) as context:
            self.handler.handle(error)
        self.assertIn("certificate", str(context.exception))

    def test_protocol_errors_explain_malformed_response(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingProtocolError("No SOAP Body"))
        self.assertIn("malformed SOAP response", str(context.exception))

    def test_application_response_errors_are_raised_if_handler_returns(self):
        transport = NordeaCARequestExecutor()
        transport._error_handler = MagicMock()
        response = MagicMock(response_code="31", response_text="Duplicate MsgId")

        with self.assertRaises(BankingResponseCodeError):
            transport._raise_application_response_error(response, "UploadFile")

        transport._error_handler.handle.assert_called_once()

    def test_invalid_application_content_is_translated(self):
        ais = NordeaCorporateAccessAIS()
        ais._error_handler = self.handler
        soap = etree.Element(f"{{{NS_SOAPENV}}}Envelope")
        body = etree.SubElement(soap, f"{{{NS_SOAPENV}}}Body")
        wire_response = etree.SubElement(body, "ApplicationResponse")
        inner_response = (
            f'<ApplicationResponse xmlns="{XMLDATA_NAMESPACE}">'
            "<Content>not-base64!</Content>"
            "</ApplicationResponse>"
        ).encode()
        wire_response.text = base64.b64encode(inner_response).decode()

        with self.assertRaises(UserError) as context:
            ais._parse_application_response(soap)

        self.assertIn("malformed SOAP response", str(context.exception))

    def test_unmapped_http_status_uses_generic_message(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingAPIError(418, "HTTP 418"))
        self.assertIn("unexpected SOAP endpoint error", str(context.exception))

    def test_unknown_response_code_uses_unrecognized_message(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingResponseCodeError("99", "Whatever"))
        self.assertIn("unrecognized application error", str(context.exception))
        self.assertIn("99", str(context.exception))

    def test_bank_message_is_appended_to_application_error(self):
        with self.assertRaises(UserError) as context:
            self.handler.handle(BankingResponseCodeError("31", "Duplicate MsgId"))
        self.assertIn("(Duplicate MsgId)", str(context.exception))

    def test_tls_error_deeper_in_cause_chain_is_detected(self):
        middle = RuntimeError("wrapped")
        middle.__cause__ = requests.exceptions.SSLError("certificate verify failed")
        error = BankingTransportError("TLS connection failed")
        error.__cause__ = middle

        with self.assertRaises(UserError) as context:
            self.handler.handle(error)
        self.assertIn("TLS authentication failed", str(context.exception))

    def test_other_transport_error_has_generic_message(self):
        error = BankingTransportError("timed out")
        error.__cause__ = requests.exceptions.ConnectTimeout("timed out")

        with self.assertRaises(UserError) as context:
            self.handler.handle(error)
        self.assertIn("could not connect to the bank", str(context.exception))

    def test_token_errors_do_not_count_as_auth_errors(self):
        self.assertFalse(self.handler.is_auth_error(BankingTokenError(401, "Unauthorized")))

class TestNordeaWSClient(BaseCase):
    def setUp(self):
        super().setUp()
        self.error_handler = MagicMock()
        self.client = NordeaWSClient("https://example.invalid", self.error_handler)
        self.client._session = MagicMock()
        self.envelope = etree.Element(f"{{{NS_SOAPENV}}}Envelope")

    def _post(self):
        return self.client.post_envelope(self.envelope, ("cert", "key"))

    def test_connection_failures_are_typed_as_transport_errors(self):
        self.client._session.request.side_effect = requests.exceptions.ConnectionError("endpoint unreachable")

        with self.assertRaises(BankingTransportError):
            self._post()
        self.error_handler.handle.assert_called_once()

    def test_malformed_soap_xml_is_a_protocol_error(self):
        self.client._session.request.return_value = MagicMock(ok=True, content=b"<soap:Envelope>")

        with self.assertRaises(BankingProtocolError):
            self._post()

    def test_http_status_is_an_api_error(self):
        self.client._session.request.return_value = MagicMock(ok=False, status_code=503, content=b"unavailable")

        with self.assertRaises(BankingAPIError) as context:
            self._post()
        self.assertEqual(context.exception.status_code, 503)

    def test_soap_fault_is_an_application_error(self):
        soap = etree.Element(f"{{{NS_SOAPENV}}}Envelope")
        body = etree.SubElement(soap, f"{{{NS_SOAPENV}}}Body")
        fault = etree.SubElement(body, f"{{{NS_SOAPENV}}}Fault")
        etree.SubElement(fault, "faultcode").text = "Client"
        etree.SubElement(fault, "faultstring").text = "Invalid signature"
        self.client._session.request.return_value = MagicMock(
            ok=False,
            status_code=500,
            content=etree.tostring(soap),
        )

        with self.assertRaises(BankingResponseCodeError):
            self._post()

    def test_malformed_application_response_is_a_protocol_error(self):
        soap = etree.Element(f"{{{NS_SOAPENV}}}Envelope")
        body = etree.SubElement(soap, f"{{{NS_SOAPENV}}}Body")
        application_response = etree.SubElement(body, "ApplicationResponse")
        application_response.text = "not-base64!"
        self.client._session.request.return_value = MagicMock(ok=True, content=etree.tostring(soap))

        with self.assertRaises(BankingProtocolError):
            self._post()

    def test_valid_application_response_is_accepted(self):
        soap = etree.Element(f"{{{NS_SOAPENV}}}Envelope")
        body = etree.SubElement(soap, f"{{{NS_SOAPENV}}}Body")
        application_response = etree.SubElement(body, "ApplicationResponse")
        inner_response = b'<ApplicationResponse xmlns="http://bxd.fi/xmldata/"/>'
        application_response.text = base64.b64encode(inner_response).decode()
        self.client._session.request.return_value = MagicMock(ok=True, content=etree.tostring(soap))

        response = self._post()

        self.assertEqual(response.tag, f"{{{NS_SOAPENV}}}Envelope")
        self.assertEqual(self.client._session.cert, ("cert", "key"))
