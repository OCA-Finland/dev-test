# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from pathlib import Path

from lxml import etree

from odoo.tests import TransactionCase

from ..tools.ir_client import build_echo
from ..tools.ir_signature import IrSignatureError, sign_document, verify_document
from .common import generate_material


class TestIrSignature(TransactionCase):
    """Enveloped signature of an Incomes Register document."""

    def test_signature_is_last_child_and_verifies(self):
        """The signature is the last child and verifies with the test key."""
        material = generate_material()
        document = sign_document(
            build_echo(), material["certificate"], material["private_key"]
        )
        self.assertEqual(
            document[-1].tag, "{http://www.w3.org/2000/09/xmldsig#}Signature"
        )
        verify_document(document, material["cert_pem"])

    def test_echo_data_is_unqualified(self):
        """Data stays outside the Echo namespace, as Echo.xsd requires."""
        material = generate_material()
        document = sign_document(
            build_echo(), material["certificate"], material["private_key"]
        )
        parsed = etree.fromstring(etree.tostring(document))
        self.assertEqual(parsed[0].tag, "Data")
        schema_path = (
            Path(__file__).resolve().parent.parent / "data" / "wsdl" / "Echo.xsd"
        )
        schema = etree.XMLSchema(etree.parse(str(schema_path)))
        schema.assertValid(parsed)

    def test_tampered_document_is_rejected(self):
        """Changing the signed payload makes verification fail."""
        material = generate_material()
        document = sign_document(
            build_echo(), material["certificate"], material["private_key"]
        )
        document[0].text = "changed"
        with self.assertRaises(IrSignatureError):
            verify_document(document, material["cert_pem"])

    def test_untrusted_certificate_is_rejected(self):
        """A valid signature from an unknown certificate is rejected."""
        material = generate_material(common_name="Signer")
        other = generate_material(common_name="Other")
        document = sign_document(
            build_echo(), material["certificate"], material["private_key"]
        )
        standalone = etree.fromstring(etree.tostring(document))
        with self.assertRaises(IrSignatureError):
            verify_document(standalone, other["cert_pem"])
