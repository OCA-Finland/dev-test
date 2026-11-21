import base64

from lxml import etree

from odoo.tests.common import BaseCase

from .....services.soap.nordea_corporate_access.nordea_ca_application_response import parse_application_response
from .....services.soap.nordea_corporate_access.constants.namespaces import XMLDATA_NAMESPACE
from .....services.soap.nordea_corporate_access.constants.application_response import (
    TAG_CUSTOMER_ID, TAG_TIMESTAMP, TAG_RESPONSE_CODE,
    TAG_RESPONSE_TEXT, TAG_EXECUTION_SERIAL, TAG_ENCRYPTED,
    TAG_COMPRESSED, TAG_COMPRESSION_METHOD, TAG_AMOUNT_TOTAL,
    TAG_TRANSACTION_COUNT, TAG_FILE_TYPE, TAG_CONTENT, TAG_APPLICATION_RESPONSE,
)

def _build_response_element(**fields) -> etree._Element:
    """Test helper: build a minimal <ApplicationResponse> with given tags/text."""
    root = etree.Element(f"{{{XMLDATA_NAMESPACE}}}{TAG_APPLICATION_RESPONSE}", nsmap={"bxd": XMLDATA_NAMESPACE})
    for tag, value in fields.items():
        el = etree.SubElement(root, f"{{{XMLDATA_NAMESPACE}}}{tag}")
        el.text = value
    return root


class TestParseApplicationResponse(BaseCase):

    def test_minimal_success_response(self):
        root = _build_response_element(**{
            TAG_CUSTOMER_ID: "12345678",
            TAG_TIMESTAMP: "2026-01-01T12:00:00Z",
            TAG_RESPONSE_CODE: "0",
            TAG_RESPONSE_TEXT: "OK",
        })
        dto = parse_application_response(root)
        self.assertEqual(dto.customer_id, "12345678")
        self.assertEqual(dto.response_code, "0")
        self.assertEqual(dto.response_text, "OK")

    def test_error_response(self):
        root = _build_response_element(**{
            TAG_CUSTOMER_ID: "12345678",
            TAG_RESPONSE_CODE: "101",
            TAG_RESPONSE_TEXT: "Invalid signature",
        })
        dto = parse_application_response(root)
        self.assertEqual(dto.response_code, "101")
        self.assertEqual(dto.response_text, "Invalid signature")

    def test_missing_optional_fields_are_none(self):
        root = _build_response_element(**{TAG_CUSTOMER_ID: "12345678"})
        dto = parse_application_response(root)
        self.assertIsNone(dto.execution_serial)
        self.assertIsNone(dto.encrypted)
        self.assertIsNone(dto.compressed)
        self.assertIsNone(dto.content)
        self.assertIsNone(dto.amount_total)
        self.assertIsNone(dto.transaction_count)

    def test_boolean_fields_parsed_correctly(self):
        root = _build_response_element(**{
            TAG_CUSTOMER_ID: "12345678",
            TAG_ENCRYPTED: "false",
            TAG_COMPRESSED: "true",
            TAG_COMPRESSION_METHOD: "GZIP",
        })
        dto = parse_application_response(root)
        self.assertEqual(dto.encrypted, False)
        self.assertEqual(dto.compressed, True)
        self.assertEqual(dto.compression_method, "GZIP")

    def test_content_is_base64_decoded(self):
        raw = b"some file content \x00\x01"
        encoded = base64.b64encode(raw).decode()
        root = _build_response_element(**{
            TAG_CUSTOMER_ID: "12345678",
            TAG_CONTENT: encoded,
        })
        dto = parse_application_response(root)
        self.assertEqual(dto.content, raw)

    def test_numeric_fields_parsed(self):
        root = _build_response_element(**{
            TAG_CUSTOMER_ID: "12345678",
            TAG_AMOUNT_TOTAL: "1234.56",
            TAG_TRANSACTION_COUNT: "42",
        })
        dto = parse_application_response(root)
        self.assertEqual(dto.amount_total, 1234.56)
        self.assertEqual(dto.transaction_count, 42)

    def test_execution_serial_and_file_type(self):
        root = _build_response_element(**{
            TAG_CUSTOMER_ID: "12345678",
            TAG_EXECUTION_SERIAL: "EXEC001",
            TAG_FILE_TYPE: "NDCAPXMLO",
        })
        dto = parse_application_response(root)
        self.assertEqual(dto.execution_serial, "EXEC001")
        self.assertEqual(dto.file_type, "NDCAPXMLO")