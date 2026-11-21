import base64

from datetime import date, datetime
from lxml import etree
from signxml import XMLVerifier

from odoo.tests.common import BaseCase

from .....services.soap.nordea_corporate_access.constants.application_request import (
    TAG_CUSTOMER_ID, TAG_COMMAND, TAG_TIMESTAMP, TAG_START_DATE,
    TAG_END_DATE, TAG_STATUS, TAG_SERVICE_ID, TAG_ENVIRONMENT,
    TAG_FILE_REFERENCES, TAG_FILE_REFERENCE, TAG_USER_FILENAME, TAG_TARGET_ID,
    TAG_EXECUTION_SERIAL, TAG_ENCRYPTION, TAG_ENCRYPTION_METHOD,
    TAG_COMPRESSION, TAG_COMPRESSION_METHOD, TAG_SOFTWARE_ID, TAG_FILE_TYPE,
    TAG_CONTENT, TAG_APPLICATION_REQUEST,
)
from .....services.soap.nordea_corporate_access.constants.namespaces import XMLDATA_NAMESPACE
from .....services.soap.nordea_corporate_access.constants.nordea_ws import FileStatus
from .....services.soap.nordea_corporate_access.nordea_ca_dtos import ApplicationRequestDTO
from .....services.soap.nordea_corporate_access.nordea_ca_application_request import (
    build_application_request,
    sign_application_request
    )
from ....test_utils import generate_self_signed_keypair

FULL_ORDER = [
    TAG_CUSTOMER_ID, TAG_COMMAND, TAG_TIMESTAMP, TAG_START_DATE, TAG_END_DATE,
    TAG_STATUS, TAG_SERVICE_ID, TAG_ENVIRONMENT, TAG_FILE_REFERENCES,
    TAG_USER_FILENAME, TAG_TARGET_ID, TAG_EXECUTION_SERIAL, TAG_ENCRYPTION,
    TAG_ENCRYPTION_METHOD, TAG_COMPRESSION, TAG_COMPRESSION_METHOD,
    TAG_SOFTWARE_ID, TAG_FILE_TYPE, TAG_CONTENT,
]

DS_NS = "http://www.w3.org/2000/09/xmldsig#"


class TestNordeaCAApplicationRequest(BaseCase):

    def _tags(self, root):
        return [etree.QName(el).localname for el in root]

    def test_root_element_name_and_namespace(self):
        dto = ApplicationRequestDTO(customer_id="12345678")
        root = build_application_request(dto)
        self.assertEqual(etree.QName(root).localname, TAG_APPLICATION_REQUEST)
        self.assertEqual(etree.QName(root).namespace, XMLDATA_NAMESPACE)

    def test_all_elements_use_bxd_namespace(self):
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            command="UploadFile",
            software_id="Test Software 1.0",
            target_id="11111111A1",
        )
        root = build_application_request(dto)
        for el in root.iter():
            self.assertEqual(etree.QName(el).namespace, XMLDATA_NAMESPACE)

    def test_minimal_dto_only_required_fields(self):
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            command="UploadFile",
            software_id="Test Software 1.0",
            target_id="11111111A1",
        )
        root = build_application_request(dto)
        tags = self._tags(root)
        self.assertEqual(tags, [TAG_CUSTOMER_ID, TAG_COMMAND, TAG_ENVIRONMENT, TAG_TARGET_ID, TAG_SOFTWARE_ID])

    def test_environment_defaults_to_production(self):
        dto = ApplicationRequestDTO(customer_id="12345678")
        root = build_application_request(dto)
        env_el = root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_ENVIRONMENT}")
        self.assertIsNotNone(env_el)
        self.assertEqual(env_el.text, "PRODUCTION")

    def test_none_fields_are_omitted_not_empty(self):
        """
        Test that all elements non-empty as specified in Secure Envelope specification:
        https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
        """
        dto = ApplicationRequestDTO(customer_id="12345678", command=None, target_id=None)
        root = build_application_request(dto)
        tags = self._tags(root)
        self.assertNotIn(TAG_COMMAND, tags)
        self.assertNotIn(TAG_TARGET_ID, tags)
        self.assertNotIn(TAG_CONTENT, tags)

    def test_full_dto_element_order(self):
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            command="DownloadFileList",
            timestamp=datetime(2026, 1, 1, 12, 0, 0),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            status=FileStatus.NEW,
            service_id="SVC1",
            environment="PRODUCTION",
            file_references=["REF1", "REF2"],
            user_filename="payment.xml",
            target_id="11111111A1",
            execution_serial="EXEC001",
            encryption=False,
            encryption_method="DES",
            compression=True,
            compression_method="GZIP",
            software_id="Test Software 1.0",
            file_type="NDCAPXMLI",
            content=b"raw file bytes",
        )
        root = build_application_request(dto)
        self.assertEqual(self._tags(root), FULL_ORDER)

    def test_file_references_nested_structure(self):
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            file_references=["REF1", "REF2", "REF3"],
        )
        root = build_application_request(dto)
        refs_el = root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_FILE_REFERENCES}")
        self.assertIsNotNone(refs_el)
        ref_tags = self._tags(refs_el)
        self.assertEqual(ref_tags, [TAG_FILE_REFERENCE, TAG_FILE_REFERENCE, TAG_FILE_REFERENCE])
        ref_values = [el.text for el in refs_el]
        self.assertEqual(ref_values, ["REF1", "REF2", "REF3"])

    def test_file_references_omitted_when_empty(self):
        dto = ApplicationRequestDTO(customer_id="12345678", file_references=None)
        root = build_application_request(dto)
        self.assertIsNone(root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_FILE_REFERENCES}"))

    # TODO this might change
    def test_content_is_base64_encoded(self):
        raw = b"some binary payload \x00\x01\x02"
        dto = ApplicationRequestDTO(customer_id="12345678", content=raw)
        root = build_application_request(dto)
        content_el = root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_CONTENT}")
        self.assertIsNotNone(content_el)
        self.assertEqual(base64.b64decode(content_el.text), raw)

    def test_encryption_boolean_serialization(self):
        for value, expected in [(True, "true"), (False, "false"), (None, None)]:
            dto = ApplicationRequestDTO(customer_id="12345678", encryption=value)
            root = build_application_request(dto)
            el = root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_ENCRYPTION}")
            if expected is None:
                self.assertIsNone(el)
            else:
                self.assertIsNotNone(el)
                self.assertEqual(el.text, expected)

    def test_compression_boolean_serialization(self):
        for value, expected in [(True, "true"), (False, "false"), (None, None)]:
            dto = ApplicationRequestDTO(customer_id="12345678", compression=value)
            root = build_application_request(dto)
            el = root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_COMPRESSION}")
            if expected is None:
                self.assertIsNone(el)
            else:
                self.assertIsNotNone(el)
                self.assertEqual(el.text, expected)

    def test_timestamp_isoformat(self):
        ts = datetime(2026, 6, 3, 14, 45, 35, 424000)
        dto = ApplicationRequestDTO(customer_id="12345678", timestamp=ts)
        root = build_application_request(dto)
        el = root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_TIMESTAMP}")
        self.assertEqual(el.text, ts.isoformat())

    def test_start_end_date_isoformat(self):
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        root = build_application_request(dto)
        start_el = root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_START_DATE}")
        end_el = root.find(f"{{{XMLDATA_NAMESPACE}}}{TAG_END_DATE}")
        self.assertEqual(start_el.text, "2026-01-01")
        self.assertEqual(end_el.text, "2026-01-31")

class TestNordeaCAApplicationRequestSigning(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_key_pem, cls.cert_pem = generate_self_signed_keypair()

    def test_signed_element_has_signature(self):
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            command="UploadFile",
            software_id="Test Software 1.0",
            target_id="11111111A1",
        )
        root = build_application_request(dto)
        signed = sign_application_request(root, self.private_key_pem, self.cert_pem)
        sig_el = signed.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
        self.assertIsNotNone(sig_el)

    def test_signature_is_verifiable(self):
        
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            command="UploadFile",
            software_id="Test Software 1.0",
            target_id="11111111A1",
        )
        root = build_application_request(dto)
        signed = sign_application_request(root, self.private_key_pem, self.cert_pem)
        # verify=True checks the signature cryptographically against the embedded cert
        XMLVerifier().verify(signed, x509_cert=self.cert_pem)

    def test_signature_contains_keyinfo_x509_certificate(self):
        """
        Nordea's Security spec requires KeyInfo -> X509Data -> X509Certificate
        inside the Signature, containing the signer's public key/cert.
        """
        dto = ApplicationRequestDTO(
            customer_id="12345678",
            command="UploadFile",
            software_id="Test Software 1.0",
            target_id="11111111A1",
        )
        root = build_application_request(dto)
        signed = sign_application_request(root, self.private_key_pem, self.cert_pem)

        sig_el = signed.find(f".//{{{DS_NS}}}Signature")
        self.assertIsNotNone(sig_el)

        key_info = sig_el.find(f"{{{DS_NS}}}KeyInfo")
        self.assertIsNotNone(key_info, "Signature must contain KeyInfo")

        x509_data = key_info.find(f"{{{DS_NS}}}X509Data")
        self.assertIsNotNone(x509_data, "KeyInfo must contain X509Data")

        x509_cert = x509_data.find(f"{{{DS_NS}}}X509Certificate")
        self.assertIsNotNone(x509_cert, "X509Data must contain X509Certificate")
        self.assertTrue(x509_cert.text and x509_cert.text.strip(), "X509Certificate must not be empty")