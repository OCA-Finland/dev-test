from odoo.tests.common import BaseCase

from .....services.constants.payments import PaymentStatus
from .....services.soap.nordea_corporate_access.nordea_ca_dtos import (
    PaymentStatusDTO,
    PaymentStatusReportDTO,
    StatusReasonDTO,
    TransactionStatusDTO,
)
from .....services.soap.nordea_corporate_access.nordea_ca_mappers import NordeaCAMappers


class TestNordeaCAPain002StatusMapping(BaseCase):
    def setUp(self):
        super().setUp()
        self.mapper = NordeaCAMappers()

    def test_acceptance_statuses_are_confirmed_but_not_terminal(self):
        for status, level in (
            ("ACCP", "payment"),
            ("ACCP", "transaction"),
            ("ACWC", "payment"),
            ("ACWC", "transaction"),
        ):
            with self.subTest(status=status, level=level):
                mapped = self.mapper._map_pain002_status(status, level)
                self.assertEqual(mapped, PaymentStatus.CONFIRMED)
                self.assertNotIn(mapped, PaymentStatus.TERMINAL)

    def test_pending_mapping_depends_on_level_and_reason(self):
        self.assertEqual(
            self.mapper._map_pain002_status("PDNG", "transaction"),
            PaymentStatus.PROCESSING,
        )
        self.assertEqual(
            self.mapper._map_pain002_status(
                "PDNG", "transaction", [StatusReasonDTO(code="AM04")]
            ),
            PaymentStatus.INSUFFICIENT_FUNDS,
        )
        # Payment-level PDNG = awaiting final confirmation by the Company
        # (Nordea MIG 7.1.3), not a funds problem.
        self.assertEqual(
            self.mapper._map_pain002_status("PDNG", "payment"),
            PaymentStatus.PENDING_USER_APPROVAL,
        )
        # The reason code must not change the payment-level result.
        self.assertEqual(
            self.mapper._map_pain002_status(
                "PDNG", "payment", [StatusReasonDTO(code="AM04")]
            ),
            PaymentStatus.PENDING_USER_APPROVAL,
        )

    def test_rejection_and_insufficient_funds_reason(self):
        self.assertEqual(
            self.mapper._map_pain002_status("RJCT", "group"),
            PaymentStatus.REJECTED,
        )
        self.assertEqual(
            self.mapper._map_pain002_status(
                "RJCT", "transaction", [StatusReasonDTO(code="AM04")]
            ),
            PaymentStatus.INSUFFICIENT_FUNDS,
        )

    def test_other_supported_statuses(self):
        self.assertEqual(
            self.mapper._map_pain002_status("ACTC", "group"),
            PaymentStatus.PROCESSING,
        )
        self.assertEqual(
            self.mapper._map_pain002_status("PART", "payment"),
            PaymentStatus.PARTIALLY_CONFIRMED,
        )

    def test_unknown_status(self):
        self.assertEqual(
            self.mapper._map_pain002_status("UNKN", "transaction"),
            PaymentStatus.UNRECOGNIZED,
        )

    def test_acsc_is_mapped_to_confirmed(self):
        # ISO-only code that Nordea does not list in MIG 7.1.3; mapped defensively.
        for level in ("group", "payment", "transaction"):
            with self.subTest(level=level):
                self.assertEqual(
                    self.mapper._map_pain002_status("ACSC", level),
                    PaymentStatus.CONFIRMED,
                )

    def test_group_level_pending_is_handled_like_transaction_level(self):
        # Not expected from Nordea (MIG 7.1.3), but ISO allows it.
        self.assertEqual(
            self.mapper._map_pain002_status("PDNG", "group"),
            PaymentStatus.PROCESSING,
        )
        self.assertEqual(
            self.mapper._map_pain002_status(
                "PDNG", "group", [StatusReasonDTO(code="AM04")]
            ),
            PaymentStatus.INSUFFICIENT_FUNDS,
        )

class TestNordeaCAPain002ReportMapping(BaseCase):
    def setUp(self):
        super().setUp()
        self.mapper = NordeaCAMappers()

    def test_group_only_report_uses_original_message_id(self):
        # Group-level ACTC carries no payment entries; correlation is by OrgnlMsgId.
        report = PaymentStatusReportDTO(
            message_id="BANKMSG1", original_message_id="PAY1", group_status="ACTC",
        )
        responses = self.mapper._map_pain002_report(report)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].banking_payment_id, "PAY1")
        self.assertEqual(responses[0].status, PaymentStatus.PROCESSING)
        self.assertEqual(responses[0].raw["level"], "group")

    def test_payment_level_pending_maps_to_pending_user_approval(self):
        report = PaymentStatusReportDTO(
            original_message_id="PAY1", group_status="ACTC",
            payments=[PaymentStatusDTO(payment_info_id="PAY1", status="PDNG")],
        )
        responses = self.mapper._map_pain002_report(report)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].status, PaymentStatus.PENDING_USER_APPROVAL)
        self.assertEqual(responses[0].raw["level"], "payment")

    def test_transaction_level_wins_over_payment_and_group(self):
        report = PaymentStatusReportDTO(
            original_message_id="PAY1", group_status="ACTC",
            payments=[PaymentStatusDTO(
                payment_info_id="PAY1", status="ACCP",
                transactions=[TransactionStatusDTO(
                    end_to_end_id="PAY1", instruction_id="PAY1", status="RJCT",
                    reasons=[StatusReasonDTO(code="NARR", additional_info=["text"])],
                )],
            )],
        )
        responses = self.mapper._map_pain002_report(report)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].status, PaymentStatus.REJECTED)
        self.assertEqual(responses[0].raw["level"], "transaction")
        self.assertEqual(responses[0].raw["reasons"][0]["additional_info"], ["text"])

    def test_entry_without_id_is_skipped(self):
        report = PaymentStatusReportDTO(group_status="ACTC")
        self.assertEqual(self.mapper._map_pain002_report(report), [])