import datetime as dt

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from lxml import etree

from odoo.tests.common import BaseCase

from ...utils.soap.xml_signing import sign_xml_enveloped, verify_xml_enveloped_signature


class TestVerifyXmlEnvelopedSignature(BaseCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Nordea Response Cert")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(dt.datetime.now(dt.timezone.utc))
            .not_valid_after(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        cls.private_key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        cls.cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()

    def _sample_element(self):
        root = etree.Element("ApplicationResponse")
        el = etree.SubElement(root, "CustomerId")
        el.text = "12345678"
        return root

    def test_valid_signature_verifies_true(self):
        signed = sign_xml_enveloped(self._sample_element(), self.private_key_pem, self.cert_pem)
        self.assertTrue(verify_xml_enveloped_signature(signed))

    def test_tampered_content_fails_verification(self):
        signed = sign_xml_enveloped(self._sample_element(), self.private_key_pem, self.cert_pem)
        # tamper with signed content after signing
        customer_id_el = signed.find("CustomerId")
        customer_id_el.text = "99999999"
        self.assertFalse(verify_xml_enveloped_signature(signed))

    def test_unsigned_element_fails_verification(self):
        unsigned = self._sample_element()
        self.assertFalse(verify_xml_enveloped_signature(unsigned))