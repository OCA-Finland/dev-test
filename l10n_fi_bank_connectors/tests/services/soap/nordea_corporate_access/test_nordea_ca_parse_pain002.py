from datetime import datetime, timezone

from odoo.tests.common import BaseCase

from .....services.soap.nordea_corporate_access.constants.pain002 import PAIN002_NAMESPACE
from .....services.soap.nordea_corporate_access.nordea_ca_pain002_parser import parse_pain002
from .....services.soap.nordea_corporate_access.nordea_ca_pain002_parser import (
    is_cancellation_reply,
    parse_pain002,
)
from ....utils.test_nca_fixtures import _minimal_pain002_xml


class TestParsePain002Group(BaseCase):

    def test_header_fields_parsed(self):
        report = parse_pain002(
            _minimal_pain002_xml(message_id="MSG42", created_at="2026-09-09T10:30:00Z")
        )
        self.assertEqual(report.message_id, "MSG42")
        self.assertEqual(
            report.created_at,
            datetime(2026, 9, 9, 10, 30, tzinfo=timezone.utc),
        )

    def test_group_accepted_has_no_reasons(self):
        report = parse_pain002(
            _minimal_pain002_xml(group_status="ACTC", original_message_id="ORIG42")
        )
        self.assertEqual(report.group_status, "ACTC")
        self.assertEqual(report.original_message_id, "ORIG42")
        self.assertEqual(report.original_message_name, "pain.001.001.09")
        self.assertEqual(report.reasons, [])

    def test_group_rejected_reason_with_repeated_additional_info(self):
        report = parse_pain002(
            _minimal_pain002_xml(
                group_status="RJCT",
                group_reasons=[("DU01", ["First text", "Second text"])],
            )
        )
        self.assertEqual(report.group_status, "RJCT")
        self.assertEqual(len(report.reasons), 1)
        self.assertEqual(report.reasons[0].code, "DU01")
        self.assertEqual(
            report.reasons[0].additional_info,
            ["First text", "Second text"],
        )

    def test_several_group_reasons_each_parsed(self):
        report = parse_pain002(
            _minimal_pain002_xml(
                group_status="RJCT",
                group_reasons=[("DU01", ["duplicate"]), ("NARR", [])],
            )
        )
        self.assertEqual([reason.code for reason in report.reasons], ["DU01", "NARR"])
        self.assertEqual(report.reasons[1].additional_info, [])

    def test_payment_level_reasons_not_in_group_reasons(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
                    <Document xmlns="{PAIN002_NAMESPACE}">
                        <CstmrPmtStsRpt>
                            <GrpHdr>
                                <MsgId>MSG001</MsgId>
                                <CreDtTm>2026-09-09T10:30:00Z</CreDtTm>
                            </GrpHdr>
                            <OrgnlGrpInfAndSts>
                                <OrgnlMsgId>ORIG001</OrgnlMsgId>
                                <OrgnlMsgNmId>pain.001.001.09</OrgnlMsgNmId>
                                <GrpSts>ACTC</GrpSts>
                            </OrgnlGrpInfAndSts>
                            <OrgnlPmtInfAndSts>
                                <OrgnlPmtInfId>PMT001</OrgnlPmtInfId>
                                <PmtInfSts>RJCT</PmtInfSts>
                                <StsRsnInf>
                                    <Rsn><Cd>AM04</Cd></Rsn>
                                    <AddtlInf>Insufficient funds</AddtlInf>
                                </StsRsnInf>
                            </OrgnlPmtInfAndSts>
                        </CstmrPmtStsRpt>
                    </Document>""".encode()
        report = parse_pain002(xml)
        self.assertEqual(report.reasons, [])

    def test_rejects_file_without_namespace(self):
        with self.assertRaises(ValueError):
            parse_pain002(_minimal_pain002_xml(namespace=None))


class TestParsePain002Payments(BaseCase):

    def test_group_only_report_has_no_payments(self):
        report = parse_pain002(
            _minimal_pain002_xml(group_status="RJCT", group_reasons=[("DU01", [])])
        )
        self.assertEqual(report.payments, [])

    def test_payment_level_only(self):
        report = parse_pain002(
            _minimal_pain002_xml(payments=[{"payment_info_id": "PMT001", "status": "ACCP"}])
        )
        self.assertEqual(len(report.payments), 1)
        payment = report.payments[0]
        self.assertEqual(payment.payment_info_id, "PMT001")
        self.assertEqual(payment.status, "ACCP")
        self.assertEqual(payment.reasons, [])
        self.assertEqual(payment.transactions, [])

    def test_transaction_level_only(self):
        report = parse_pain002(
            _minimal_pain002_xml(
                payments=[{
                    "payment_info_id": "PMT001",
                    "transactions": [{
                        "end_to_end_id": "E2E001",
                        "instruction_id": "INSTR001",
                        "status": "ACCP",
                    }],
                }]
            )
        )
        payment = report.payments[0]
        self.assertIsNone(payment.status)
        transaction = payment.transactions[0]
        self.assertEqual(transaction.end_to_end_id, "E2E001")
        self.assertEqual(transaction.instruction_id, "INSTR001")
        self.assertEqual(transaction.status, "ACCP")

    def test_combined_levels_keep_reasons_at_their_own_level(self):
        report = parse_pain002(
            _minimal_pain002_xml(
                payments=[{
                    "payment_info_id": "PMT001",
                    "status": "PDNG",
                    "reasons": [("NARR", ["Payment level text"])],
                    "transactions": [{
                        "end_to_end_id": "E2E001",
                        "instruction_id": "INSTR001",
                        "status": "RJCT",
                        "reasons": [("AM04", ["First tx text", "Second tx text"])],
                    }],
                }]
            )
        )
        payment = report.payments[0]
        self.assertEqual(payment.status, "PDNG")
        self.assertEqual([reason.code for reason in payment.reasons], ["NARR"])
        self.assertEqual(payment.reasons[0].additional_info, ["Payment level text"])

        transaction = payment.transactions[0]
        self.assertEqual(transaction.status, "RJCT")
        self.assertEqual([reason.code for reason in transaction.reasons], ["AM04"])
        self.assertEqual(
            transaction.reasons[0].additional_info,
            ["First tx text", "Second tx text"],
        )

    def test_several_payments_and_transactions_keep_order(self):
        report = parse_pain002(
            _minimal_pain002_xml(
                payments=[
                    {
                        "payment_info_id": "PMT001",
                        "transactions": [
                            {"end_to_end_id": "E2E001", "status": "ACCP"},
                            {"end_to_end_id": "E2E002", "status": "RJCT"},
                        ],
                    },
                    {
                        "payment_info_id": "PMT002",
                        "transactions": [{"end_to_end_id": "E2E003", "status": "PDNG"}],
                    },
                ]
            )
        )
        self.assertEqual(
            [payment.payment_info_id for payment in report.payments],
            ["PMT001", "PMT002"],
        )
        first = report.payments[0].transactions
        self.assertEqual([tx.end_to_end_id for tx in first], ["E2E001", "E2E002"])
        self.assertEqual([tx.status for tx in first], ["ACCP", "RJCT"])
        second = report.payments[1].transactions
        self.assertEqual([tx.end_to_end_id for tx in second], ["E2E003"])

    def test_missing_optional_transaction_fields_are_none(self):
        report = parse_pain002(
            _minimal_pain002_xml(
                payments=[{
                    "payment_info_id": "PMT001",
                    "transactions": [{"end_to_end_id": "E2E001"}],
                }]
            )
        )
        transaction = report.payments[0].transactions[0]
        self.assertEqual(transaction.end_to_end_id, "E2E001")
        self.assertIsNone(transaction.instruction_id)
        self.assertIsNone(transaction.status)
        self.assertEqual(transaction.reasons, [])


class TestParsePain002Rejections(BaseCase):

    def test_rejects_empty_content(self):
        with self.assertRaises(ValueError):
            parse_pain002(b"")

    def test_rejects_malformed_xml(self):
        with self.assertRaises(ValueError):
            parse_pain002(b"<Document><unclosed>")

    def test_rejects_unsupported_version_and_names_namespace(self):
        old_namespace = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.03"
        with self.assertRaises(ValueError) as ctx:
            parse_pain002(_minimal_pain002_xml(namespace=old_namespace))
        self.assertIn(old_namespace, str(ctx.exception))

    def test_rejects_document_without_status_report(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
                    <Document xmlns="{PAIN002_NAMESPACE}">
                        <BkToCstmrStmt/>
                    </Document>""".encode()
        with self.assertRaises(ValueError):
            parse_pain002(xml)


class TestIsCancellationReply(BaseCase):

    def test_camt055_reply_is_detected_and_group_level_still_parsed(self):
        report = parse_pain002(
            _minimal_pain002_xml(
                original_message_name="camt.055.001.08",
                group_status="RJCT",
                group_reasons=[("NARR", ["Cancellation request rejected"])],
            )
        )
        self.assertTrue(is_cancellation_reply(report))
        self.assertEqual(report.group_status, "RJCT")
        self.assertEqual(report.reasons[0].code, "NARR")

    def test_pain001_reply_is_not_a_cancellation_reply(self):
        report = parse_pain002(_minimal_pain002_xml(original_message_name="pain.001.001.09"))
        self.assertFalse(is_cancellation_reply(report))

    def test_missing_message_name_is_not_a_cancellation_reply(self):
        report = parse_pain002(_minimal_pain002_xml(original_message_name=""))
        self.assertIsNone(report.original_message_name)
        self.assertFalse(is_cancellation_reply(report))