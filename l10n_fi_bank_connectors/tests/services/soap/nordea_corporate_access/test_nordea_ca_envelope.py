import base64

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from datetime import datetime, timedelta, timezone
from lxml import etree

from odoo.tests.common import BaseCase

from .....services.soap.nordea_corporate_access.nordea_ca_application_request import (
    build_application_request,
    sign_application_request,
)
from .....services.soap.nordea_corporate_access.nordea_ca_dtos import (
    ApplicationRequestDTO,
    RequestHeaderDTO,
)
from .....services.soap.nordea_corporate_access.nordea_ca_envelope import build_upload_file_envelope
from .....services.soap.nordea_corporate_access.constants.namespaces import NS_SOAPENV, NS_MODEL, NS_SERVICE
from .....services.soap.nordea_corporate_access.constants.soap_envelope import (
    TAG_ENVELOPE, TAG_BODY, TAG_UPLOAD_FILE_IN, TAG_REQUEST_HEADER,
    TAG_APPLICATION_REQUEST, TAG_SENDER_ID, TAG_REQUEST_ID, TAG_TIMESTAMP,
    TAG_LANGUAGE, TAG_USER_AGENT, TAG_RECEIVER_ID,
)


class TestNordeaCAEnvelope(BaseCase):

    def _sample_signed_app_request(self):
        # Reuses an unsigned element — envelope builder doesn't care whether
        # it's signed, it just base64-encodes whatever element it's given.
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            command="UploadFile",
            software_id="Test Software 1.0",
            target_id="11111111A1",
        )
        return build_application_request(dto)

    def test_envelope_root_and_body(self):
        header = RequestHeaderDTO(
            sender_id="12345678",
            request_id="REQ001",
            timestamp=datetime(2026, 1, 1, 12, 0, 0),
            receiver_id="NDEAFIHH",
        )
        envelope = build_upload_file_envelope(header, self._sample_signed_app_request())

        self.assertEqual(etree.QName(envelope).localname, TAG_ENVELOPE)
        self.assertEqual(etree.QName(envelope).namespace, NS_SOAPENV)

        body = envelope.find(f"{{{NS_SOAPENV}}}{TAG_BODY}")
        self.assertIsNotNone(body)

        upload_in = body.find(f"{{{NS_SERVICE}}}{TAG_UPLOAD_FILE_IN}")
        self.assertIsNotNone(upload_in)

    def test_request_header_fields_and_namespace(self):
        header = RequestHeaderDTO(
            sender_id="12345678",
            request_id="REQ001",
            timestamp=datetime(2026, 1, 1, 12, 0, 0),
            receiver_id="NDEAFIHH",
            language="FI",
            user_agent="OdooBankingConnector/1.0",
        )
        envelope = build_upload_file_envelope(header, self._sample_signed_app_request())
        upload_in = envelope.find(f".//{{{NS_SERVICE}}}{TAG_UPLOAD_FILE_IN}")
        header_el = upload_in.find(f"{{{NS_MODEL}}}{TAG_REQUEST_HEADER}")
        self.assertIsNotNone(header_el)

        tags = [etree.QName(el).localname for el in header_el]
        self.assertEqual(tags, [
            TAG_SENDER_ID, TAG_REQUEST_ID, TAG_TIMESTAMP,
            TAG_LANGUAGE, TAG_USER_AGENT, TAG_RECEIVER_ID,
        ])
        for el in header_el:
            self.assertEqual(etree.QName(el).namespace, NS_MODEL)

        self.assertEqual(header_el.find(f"{{{NS_MODEL}}}{TAG_SENDER_ID}").text, "12345678")
        self.assertEqual(header_el.find(f"{{{NS_MODEL}}}{TAG_RECEIVER_ID}").text, "NDEAFIHH")

    def test_request_header_omits_nillable_fields_when_unset(self):
        header = RequestHeaderDTO(
            sender_id="12345678",
            request_id="REQ001",
            timestamp=datetime(2026, 1, 1, 12, 0, 0),
            receiver_id="NDEAFIHH",
            # language / user_agent left unset
        )
        envelope = build_upload_file_envelope(header, self._sample_signed_app_request())
        header_el = envelope.find(f".//{{{NS_MODEL}}}{TAG_REQUEST_HEADER}")
        tags = [etree.QName(el).localname for el in header_el]
        self.assertNotIn(TAG_LANGUAGE, tags)
        self.assertNotIn(TAG_USER_AGENT, tags)

    def test_application_request_is_base64_encoded_xml(self):
        header = RequestHeaderDTO(
            sender_id="12345678",
            request_id="REQ001",
            timestamp=datetime(2026, 1, 1, 12, 0, 0),
            receiver_id="NDEAFIHH",
        )
        app_request_el = self._sample_signed_app_request()
        envelope = build_upload_file_envelope(header, app_request_el)

        encoded_el = envelope.find(f".//{{{NS_SERVICE}}}{TAG_APPLICATION_REQUEST}")
        self.assertIsNotNone(encoded_el)

        decoded_bytes = base64.b64decode(encoded_el.text)
        # round-trip: decoded bytes should re-parse as valid XML matching
        # the original ApplicationRequest element
        reparsed = etree.fromstring(decoded_bytes)
        self.assertEqual(etree.QName(reparsed).localname, "ApplicationRequest")
        self.assertEqual(
            reparsed.find(f"{{http://bxd.fi/xmldata/}}CustomerId").text,
            "12345678",
        )

    def test_signed_application_request_round_trips_with_signature(self):
        """End-to-end: build -> sign -> embed in envelope -> decode -> Signature intact."""
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            command="UploadFile",
            software_id="Test Software 1.0",
            target_id="11111111A1",
        )
        root = build_application_request(dto)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        # minimal self-signed cert reused inline for this one test
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        private_key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()

        signed = sign_application_request(root, private_key_pem, cert_pem)

        header = RequestHeaderDTO(
            sender_id="12345678",
            request_id="REQ001",
            timestamp=datetime(2026, 1, 1, 12, 0, 0),
            receiver_id="NDEAFIHH",
        )
        envelope = build_upload_file_envelope(header, signed)
        encoded_el = envelope.find(f".//{{{NS_SERVICE}}}{TAG_APPLICATION_REQUEST}")
        decoded = etree.fromstring(base64.b64decode(encoded_el.text))

        sig_el = decoded.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
        self.assertIsNotNone(sig_el)