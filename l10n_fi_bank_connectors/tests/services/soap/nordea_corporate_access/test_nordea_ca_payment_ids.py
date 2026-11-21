from decimal import Decimal
from lxml import etree
from unittest.mock import MagicMock

from odoo.tests.common import BaseCase

from .....services.soap.nordea_corporate_access.constants.pain001 import PAIN001_NAMESPACE
from .....services.soap.nordea_corporate_access.nordea_ca_dtos import NordeaCAPaymentRequestDTO
from .....services.soap.nordea_corporate_access.nordea_ca_payment_payload import build_pain001_payload
from .....services.soap.nordea_corporate_access.nordea_ca_pis import NordeaCAPIS
from .....utils.id_generation import generate_unique_id


def _dto(payment_id):
    return NordeaCAPaymentRequestDTO(
        creditor_name="Creditor",
        creditor_iban="FI7429501800000014",
        debtor_iban="FI2112345600000785",
        debtor_name="Debtor Oy",
        amount=Decimal("10.00"),
        currency="EUR",
        reference="",
        message="Test",
        end_to_end_id=payment_id,
    )


def _payload_ids(xml):
    """The four identifiers of the generated pain.001, keyed by their XML tag."""
    root = etree.fromstring(xml)
    ns = {"p": PAIN001_NAMESPACE}
    return {
        "MsgId": root.findtext(".//p:GrpHdr/p:MsgId", namespaces=ns),
        "PmtInfId": root.findtext(".//p:PmtInf/p:PmtInfId", namespaces=ns),
        "InstrId": root.findtext(".//p:CdtTrfTxInf/p:PmtId/p:InstrId", namespaces=ns),
        "EndToEndId": root.findtext(".//p:CdtTrfTxInf/p:PmtId/p:EndToEndId", namespaces=ns),
    }


class TestPain001PaymentIds(BaseCase):

    def test_all_four_ids_carry_the_payment_id(self):
        ids = _payload_ids(build_pain001_payload(_dto("PAYMENT-ID-1")))
        self.assertEqual(ids, {
            "MsgId": "PAYMENT-ID-1",
            "PmtInfId": "PAYMENT-ID-1",
            "InstrId": "PAYMENT-ID-1",
            "EndToEndId": "PAYMENT-ID-1",
        })

    def test_ids_are_stable_across_builds(self):
        # MsgId and PmtInfId used to be random on every build, so they could not be
        # matched against the pain.002 reports Nordea sends back.
        dto = _dto("PAYMENT-ID-2")
        self.assertEqual(
            _payload_ids(build_pain001_payload(dto)),
            _payload_ids(build_pain001_payload(dto)),
        )

    def test_generated_id_fits_the_35_character_limit(self):
        # Nordea requires these identifiers to be a string of at most 35 characters.
        self.assertLessEqual(len(generate_unique_id()), 35)


class TestGenerateUniqueIdentification(BaseCase):

    def test_generates_and_flushes_when_empty(self):
        payment = MagicMock()
        payment.banking_payment_id = ""
        NordeaCAPIS().generate_unique_identification(payment)
        self.assertTrue(payment.banking_payment_id)
        payment.flush_recordset.assert_called_once_with(['banking_payment_id'])

    def test_keeps_existing_id_when_payment_is_sent_again(self):
        payment = MagicMock()
        payment.banking_payment_id = "EXISTING-ID"
        NordeaCAPIS().generate_unique_identification(payment)
        self.assertEqual(payment.banking_payment_id, "EXISTING-ID")
        payment.flush_recordset.assert_not_called()

    def test_stored_id_is_passed_to_the_request_dto(self):
        payment = MagicMock()
        payment.banking_payment_id = "ID-3"
        self.assertEqual(
            NordeaCAPIS().extra_payment_request_kwargs(payment),
            {"end_to_end_id": "ID-3"},
        )