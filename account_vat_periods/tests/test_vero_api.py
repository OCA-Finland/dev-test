import copy
from datetime import date
from unittest.mock import Mock, patch

import requests

from odoo import Command, _
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from .. import vero_payload as p
from ..models import vero_backend
from ..models.vero_backend import INTERNAL
from ..models.vero_report import MisReportInstance


@tagged("post_install", "-at_install", "vero_api")
class TestVeroAPI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.vat = "FI99999992"
        cls.user = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Vero full accounting test",
                    "login": "vero_full_test",
                    "company_id": cls.company.id,
                    "company_ids": [Command.set([cls.company.id])],
                    "groups_id": [
                        Command.set([cls.env.ref("account.group_account_user").id])
                    ],
                }
            )
        )
        cls.reader = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Vero readonly test",
                    "login": "vero_readonly_test",
                    "company_id": cls.company.id,
                    "company_ids": [Command.set([cls.company.id])],
                    "groups_id": [
                        Command.set([cls.env.ref("account.group_account_readonly").id])
                    ],
                }
            )
        )
        cls.backend = cls.env["vero.api.backend"].create(
            {
                "name": "Vero isolated test",
                "company_id": cls.company.id,
                "environment": "sandbox",
                "contact_name": "Test User",
                "contact_phone": "+358401234567",
            }
        )
        range_type = cls.env["date.range.type"].create({"name": "Vero test months"})
        date_range = cls.env["date.range"].create(
            {
                "name": "Vero 2026-03",
                "type_id": range_type.id,
                "date_start": "2026-03-01",
                "date_end": "2026-03-31",
                "company_id": cls.company.id,
            }
        )
        cls.period = cls.env["account.vat.period"].create(
            {"date_range_id": date_range.id, "closed": True}
        )
        cls.report = (
            cls.env["vero.api.report"]
            .with_context(_vero_internal=INTERNAL)
            .create(
                {
                    "company_id": cls.company.id,
                    "backend_id": cls.backend.id,
                    "vat_period_id": cls.period.id,
                    "kind": "vat",
                    "date_start": "2026-03-01",
                    "date_end": "2026-03-31",
                }
            )
        )

    def payload(self, tax=100, deduction=20):
        values = dict.fromkeys(p.VAT_MAPPING, 0)
        values.update(vero_25_5=tax, verokauden_vahennettava_vero=deduction)
        return p.vat_payload(
            values, "FI99999992", "2026-03-31", p.contact("Test User", "+358401234567")
        )

    def test_normal_and_refundable_vat(self):
        self.assertEqual(p.payable(self.payload()), 80)
        self.assertEqual(p.payable(self.payload(10, 50)), -40)
        self.assertEqual(
            self.payload()["VATDetails"]["VATOnDomesticSalesByTaxRate"]["HighVATRate"],
            100,
        )
        self.assertEqual(p.money("1.005"), 1.01)
        self.assertEqual(p.money("-1.005"), -1.01)

    def test_sandbox_transport_headers_without_certificate(self):
        with patch.object(
            type(self.backend), "_secret", return_value="test-subscription-key"
        ):
            root, headers, cert = self.backend.with_user(self.user)._connection()
        self.assertEqual(root, "https://api-sandbox.vero.fi/Return/SAT")
        self.assertEqual(headers["Ocp-Apim-Subscription-Key"], "test-subscription-key")
        self.assertEqual(headers["Vero-SoftwareKey"], "sandbox")
        self.assertIsNone(cert)

    def test_zero_and_missing_values(self):
        values = dict.fromkeys(p.VAT_MAPPING, 0)
        body = p.vat_payload(
            values, "9999999-2", "2026-03-31", p.contact("Test", "+3581"), True
        )
        self.assertTrue(body["NoActivity"])
        self.assertNotIn("VATDetails", body)
        del values["vero_25_5"]
        with self.assertRaises(ValueError):
            p.vat_payload(
                values, "9999999-2", "2026-03-31", p.contact("Test", "+3581"), True
            )

    def test_ec_correction_removes_old_identifier(self):
        old = p.ec_payload(
            [
                {
                    "CountryCode": "SE",
                    "VATIdentifier": "123456789001",
                    "SalesOfGoods": 100,
                    "SalesOfServices": 20,
                    "TriangulationSales": 0,
                }
            ],
            "9999999-2",
            date(2026, 3, 1),
            p.contact("Test", "+3581"),
        )
        new = p.ec_payload(
            [
                {
                    "CountryCode": "DE",
                    "VATIdentifier": "123456789",
                    "SalesOfGoods": 80,
                    "SalesOfServices": 0,
                    "TriangulationSales": 0,
                }
            ],
            "9999999-2",
            date(2026, 3, 1),
            p.contact("Test", "+3581"),
        )
        result = p.ec_correction(new, old)
        self.assertEqual(len(result["Buyers"]), 2)
        cleared = next(row for row in result["Buyers"] if row["CountryCode"] == "SE")
        self.assertEqual([cleared[f] for f in p.SALES_FIELDS], [0, 0, 0])
        self.assertFalse(p.ec_correction(old, old)["Buyers"])

    def test_line_changes_with_same_total_are_detected(self):
        before, after = self.payload(), self.payload(120, 40)
        self.assertEqual(p.payable(before), p.payable(after))
        self.assertNotEqual(p.digest(before), p.digest(after))
        self.assertEqual(len(p.differences(before, after)), 2)

    def test_readonly_cannot_preview_or_configure(self):
        with self.assertRaises(AccessError):
            self.report.with_user(self.reader).action_preview()
        with self.assertRaises(AccessError):
            self.backend.with_user(self.reader).write({"contact_name": "Not allowed"})
        with self.assertRaises(AccessError):
            self.period.with_user(self.reader).action_do_send()
        with self.assertRaises(AccessError):
            self.report.with_user(self.reader).action_fetch_status()

    def test_history_cannot_be_forged(self):
        with self.assertRaises(AccessError):
            self.report.with_user(self.user).write({"remote_status": "Processed"})
        with self.assertRaises(AccessError):
            self.env["vero.api.submission"].with_user(self.user).create(
                {"report_id": self.report.id}
            )

    def test_duplicate_and_uncertain_submission(self):
        body = self.payload()
        wizard = (
            self.env["vero.api.wizard"]
            .with_user(self.user)
            .create({"report_id": self.report.id, "snapshot": body})
        )
        with (
            patch.object(
                type(self.backend),
                "_connection",
                return_value=("https://api-sandbox.vero.fi/Return/SAT", {}, None),
            ),
            patch.object(type(self.report), "_payload", return_value=body),
        ):
            wizard.action_refresh()
            wizard.action_submit()
            with self.assertRaises(UserError):
                wizard.action_submit()
            attempt = self.report.submission_ids[:1]
            attempt._update(state="uncertain")
            with self.assertRaises(UserError):
                wizard.action_submit()
        self.assertEqual(len(self.report.submission_ids), 1)

    def test_only_receipt_is_success(self):
        self.assertFalse(p.received_response(200, {"Status": "Processed"}))
        self.assertFalse(
            p.received_response(
                500, {"UniqueIdentifier": "x", "AcceptedTimestamp": "today"}
            )
        )
        self.assertTrue(
            p.received_response(
                200, {"UniqueIdentifier": "x", "AcceptedTimestamp": "today"}
            )
        )

    def test_other_company_denied(self):
        other = self.env["res.company"].create({"name": "Vero other company"})
        backend = self.env["vero.api.backend"].create(
            {
                "name": "Other connection",
                "company_id": other.id,
                "contact_name": "Other",
                "contact_phone": "+3581",
            }
        )
        with self.assertRaises(AccessError):
            backend.with_user(self.user).with_context(
                allowed_company_ids=[self.company.id]
            )._connection()

    def test_installed_mis_mapping(self):
        # Exercise the real configured MIS template rather than a mirrored calculator.
        values = self.report._mis_values()
        self.assertTrue(set(p.VAT_MAPPING).issubset(values))
        result = self.report._payload()
        self.assertIn("VATDetails", result)
        self.assertEqual(result["BusinessId"], "9999999-2")

    def attempt(self, body=None):
        body = body or self.payload()
        return (
            self.env["vero.api.submission"]
            .with_context(_vero_internal=INTERNAL)
            .create(
                {
                    "report_id": self.report.id,
                    "requested_by_id": self.user.id,
                    "environment": "sandbox",
                    "snapshot": body,
                    "request_body": body,
                    "content_hash": p.digest(body),
                    "state": "accepted",
                    "receipt": "unit-test-receipt",
                }
            )
            .with_user(self.user)
        )

    def test_bill_creation_and_draft_correction(self):
        self.report.with_context(_vero_internal=INTERNAL).write(
            {"due_date": "2026-05-12"}
        )
        first = self.attempt()
        first._sync_bill()
        original = first.bill_id
        self.assertEqual(original.amount_total, 80)
        self.assertEqual(original.state, "draft")
        first._sync_bill()
        self.assertEqual(self.period.payment_move_id, original)
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        self.assertEqual(original.state, "cancel")
        self.assertEqual(correction.bill_id.amount_total, 180)
        self.assertNotEqual(correction.bill_id, original)
        self.assertEqual(original.company_id, self.company)

    def test_refund_cancels_draft_without_payable_bill(self):
        self.report.with_context(_vero_internal=INTERNAL).write(
            {"due_date": "2026-05-12"}
        )
        first = self.attempt()
        first._sync_bill()
        refund = self.attempt(self.payload(10, 50))
        refund._sync_bill()
        self.assertEqual(first.bill_id.state, "cancel")
        self.assertFalse(self.period.payment_move_id)
        self.assertFalse(refund.bill_id)

    def test_posted_bill_requires_visible_manual_adjustment(self):
        self.report.with_context(_vero_internal=INTERNAL).write(
            {"due_date": "2026-05-12"}
        )
        first = self.attempt()
        first._sync_bill()
        first.bill_id.action_post()
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        self.assertEqual(first.bill_id.state, "posted")
        self.assertEqual(first.bill_id.amount_total, 80)
        self.assertTrue(correction.bill_message)
        self.assertFalse(correction.bill_id)
        self.assertEqual(correction.state, "accepted")

    def test_correction_reason_requires_fresh_preview(self):
        self.attempt()
        body = self.payload(200, 20)
        wizard = (
            self.env["vero.api.wizard"]
            .with_user(self.user)
            .create({"report_id": self.report.id, "replacement_reason": "CLC"})
        )
        with (
            patch.object(
                type(self.backend), "_connection", return_value=("", {}, None)
            ),
            patch.object(type(self.report), "_payload", return_value=body),
        ):
            wizard.action_refresh()
            self.assertTrue(wizard.preview_body["ReplacementReturn"])
            wizard.replacement_reason = "LAW"
            with self.assertRaises(UserError):
                wizard.action_submit()
            wizard.action_refresh()
            wizard.action_submit()
        self.assertEqual(
            self.report.submission_ids.sorted("id", reverse=True)[:1].request_body[
                "ReplacementReason"
            ],
            "LAW",
        )

    def test_connection_identity_is_frozen(self):
        with self.assertRaises(UserError):
            self.backend.write({"environment": "production"})

    def test_old_status_response_does_not_accept_uncertain_attempt(self):
        attempt = self.attempt()
        attempt._update(state="uncertain", receipt=False)
        with patch.object(
            type(self.backend), "_call", return_value=(200, {"Status": "Processed"})
        ):
            self.report.with_user(self.user).action_fetch_status()
        self.assertEqual(attempt.state, "uncertain")
        self.assertFalse(self.period.vero_vat_received)

    def test_uncertain_resolution_is_audited_and_not_resent(self):
        attempt = self.attempt()
        attempt._update(state="uncertain", receipt=False, error_message="Timeout")
        wizard = (
            self.env["vero.api.resolution"]
            .with_user(self.user)
            .create(
                {
                    "submission_id": attempt.id,
                    "result": "received",
                    "note": "Verified with Vero test support",
                }
            )
        )
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.write(
            {
                "receipt": "verified-test-receipt",
                "accepted_timestamp": "2026-09-17T12:00:00Z",
            }
        )
        wizard.action_confirm()
        self.assertEqual(attempt.state, "accepted")
        self.assertEqual(attempt.resolved_by_id, self.user)
        self.assertEqual(attempt.error_message, "Timeout")
        self.assertFalse(attempt.bill_id)
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_ec_source_refund_and_missing_identifier(self):
        goods, services = self.env["account.account.tag"].create(
            [
                {"name": "Vero test goods", "applicability": "taxes"},
                {"name": "Vero test services", "applicability": "taxes"},
            ]
        )
        self.backend.write(
            {
                "goods_tag_ids": [Command.set(goods.ids)],
                "services_tag_ids": [Command.set(services.ids)],
            }
        )
        partner = (
            self.env["res.partner"]
            .with_context(no_vat_validation=True)
            .create({"name": "EU test buyer", "vat": "SE123456789001"})
        )
        account = self.env["account.account"].search(
            [("company_ids", "in", self.company.id), ("account_type", "=", "income")],
            limit=1,
        )
        journal = self.env["account.journal"].search(
            [("company_id", "=", self.company.id), ("type", "=", "general")], limit=1
        )
        move = self.env["account.move"].create(
            {
                "journal_id": journal.id,
                "date": "2026-03-15",
                "line_ids": [
                    Command.create(
                        {
                            "name": "EC sale",
                            "account_id": account.id,
                            "partner_id": partner.id,
                            "credit": 100,
                            "tax_tag_ids": [Command.set(goods.ids)],
                        }
                    ),
                    Command.create(
                        {
                            "name": "EC credit",
                            "account_id": account.id,
                            "partner_id": partner.id,
                            "debit": 20,
                            "tax_tag_ids": [Command.set(goods.ids)],
                        }
                    ),
                    Command.create(
                        {
                            "name": "Balance",
                            "account_id": self.company.vat_account_id.id,
                            "debit": 80,
                        }
                    ),
                ],
            }
        )
        move.action_post()
        rows = self.report.with_user(self.user)._ec_buyers()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["SalesOfGoods"], 80)
        self.assertEqual(rows[0]["VATIdentifier"], "123456789001")
        partner.vat = False
        with self.assertRaises(UserError):
            self.report.with_user(self.user)._ec_buyers()

    def test_period_view_hides_legacy_button(self):
        view = self.period.with_user(self.user).get_view(view_type="list")
        self.assertNotIn("action_file_statement", view["arch"])
        self.assertIn("vero_vat_received", view["arch"])
        self.period.with_user(self.user).read(["vero_status", "payment_state"])

    def test_paid_bill_and_payment_are_preserved_on_correction(self):
        self.report.with_context(_vero_internal=INTERNAL).write(
            {"due_date": "2026-05-12"}
        )
        first = self.attempt()
        first._sync_bill()
        bill = first.bill_id
        bill.action_post()
        payable = bill.line_ids.filtered(
            lambda line: line.account_id.account_type == "liability_payable"
        )
        bank = self.env["account.account"].search(
            [
                ("company_ids", "in", self.company.id),
                ("account_type", "=", "asset_cash"),
            ],
            limit=1,
        )
        journal = self.env["account.journal"].search(
            [("company_id", "=", self.company.id), ("type", "=", "general")], limit=1
        )
        payment = self.env["account.move"].create(
            {
                "journal_id": journal.id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "Test payment",
                            "account_id": payable.account_id.id,
                            "partner_id": bill.partner_id.id,
                            "debit": 80,
                        }
                    ),
                    Command.create(
                        {"name": "Bank", "account_id": bank.id, "credit": 80}
                    ),
                ],
            }
        )
        payment.action_post()
        (
            payable
            | payment.line_ids.filtered(
                lambda line: line.account_id == payable.account_id
            )
        ).reconcile()
        self.assertEqual(bill.amount_residual, 0)
        reconciliation = payable.full_reconcile_id
        self.assertTrue(reconciliation)
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        self.assertEqual(bill.state, "posted")
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(payable.full_reconcile_id, reconciliation)
        self.assertEqual(payment.state, "posted")
        self.assertTrue(correction.bill_message)
        self.assertEqual(correction.state, "accepted")

        correction.action_prepare_bill_adjustment()
        credit, replacement = correction.credit_note_id, correction.bill_id
        self.assertEqual(credit.state, "draft")
        self.assertEqual(credit.amount_total, 80)
        self.assertEqual(replacement.state, "draft")
        self.assertEqual(replacement.amount_total, 180)
        self.assertEqual(payable.full_reconcile_id, reconciliation)
        correction.action_prepare_bill_adjustment()
        self.assertEqual(correction.credit_note_id, credit)
        self.assertEqual(correction.bill_id, replacement)
        # Accounting user's explicit posting and allocation produce the net debt.
        (credit | replacement).action_post()
        (credit | replacement).line_ids.filtered(
            lambda line: line.account_id.account_type == "liability_payable"
        ).reconcile()
        self.assertEqual(replacement.amount_residual, 100)
        self.assertEqual(credit.amount_residual, 0)
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(payable.full_reconcile_id, reconciliation)

    def test_zero_return_produces_no_payable_bill(self):
        body = p.vat_payload(
            dict.fromkeys(p.VAT_MAPPING, 0),
            "9999999-2",
            "2026-03-31",
            p.contact("Test", "+3581"),
            True,
        )
        attempt = self.attempt(body)
        attempt._sync_bill()
        self.assertFalse(attempt.bill_id)
        self.assertFalse(self.period.payment_move_id)
        self.assertTrue(self.period.vero_vat_received)

    def test_correction_after_refund_preserves_prepared_credit(self):
        self.report.with_context(_vero_internal=INTERNAL).write(
            {"due_date": "2026-05-12"}
        )
        first = self.attempt()
        first._sync_bill()
        first.bill_id.action_post()
        refund = self.attempt(self.payload(10, 50))
        refund._sync_bill()
        refund.action_prepare_bill_adjustment()
        credit = refund.credit_note_id
        self.assertFalse(refund.bill_id)
        later = self.attempt(self.payload(120, 20))
        later._sync_bill()
        self.assertEqual(credit.state, "draft")
        self.assertEqual(later.credit_note_id, credit)
        self.assertEqual(later.bill_id.amount_total, 100)
        self.assertEqual(first.bill_id.state, "posted")

    def test_ec_queue_is_independent_and_correction_sends_only_changes(self):
        self.period.closed = False
        report = (
            self.env["vero.api.report"]
            .with_context(_vero_internal=INTERNAL)
            .create(
                {
                    "company_id": self.company.id,
                    "backend_id": self.backend.id,
                    "vat_period_id": self.period.id,
                    "kind": "ec",
                    "date_start": "2026-03-01",
                    "date_end": "2026-03-31",
                }
            )
        )
        body = p.ec_payload(
            [
                {
                    "CountryCode": "SE",
                    "VATIdentifier": "123456789001",
                    "SalesOfGoods": 100,
                    "SalesOfServices": 0,
                    "TriangulationSales": 0,
                },
                {
                    "CountryCode": "DE",
                    "VATIdentifier": "123456789",
                    "SalesOfGoods": 200,
                    "SalesOfServices": 0,
                    "TriangulationSales": 0,
                },
            ],
            "9999999-2",
            date(2026, 3, 1),
            p.contact("Test", "+3581"),
        )
        wizard = (
            self.env["vero.api.wizard"]
            .with_user(self.user)
            .create({"report_id": report.id})
        )
        with (
            patch.object(
                type(self.backend), "_connection", return_value=("", {}, None)
            ),
            patch.object(
                type(report), "_payload", side_effect=lambda **kw: copy.deepcopy(body)
            ),
        ):
            wizard.action_refresh()
            wizard.action_submit()
            first = report.submission_ids.sorted("id", reverse=True)[:1]
            first._update(state="accepted", receipt="EC-receipt")
            body["Buyers"][0]["SalesOfGoods"] = 250
            wizard.action_refresh()
            self.assertEqual(len(wizard.preview_body["Buyers"]), 1)
            wizard.action_submit()
        self.assertEqual(len(report.submission_ids), 2)
        self.assertFalse(self.report.submission_ids)
        self.assertFalse(self.period.payment_move_id)

    def test_changed_source_requires_new_preview(self):
        wizard = (
            self.env["vero.api.wizard"]
            .with_user(self.user)
            .create({"report_id": self.report.id})
        )
        with (
            patch.object(
                type(self.backend), "_connection", return_value=("", {}, None)
            ),
            patch.object(
                type(self.report),
                "_payload",
                side_effect=[self.payload(), self.payload(200, 20)],
            ),
        ):
            wizard.action_refresh()
            with self.assertRaises(UserError):
                wizard.action_submit()
        self.assertFalse(self.report.submission_ids)
        self.assertEqual(wizard.snapshot, self.payload())

    def test_unchanged_correction_is_not_queued(self):
        first = self.attempt()
        wizard = (
            self.env["vero.api.wizard"]
            .with_user(self.user)
            .create({"report_id": self.report.id, "replacement_reason": "CLC"})
        )
        with (
            patch.object(
                type(self.backend), "_connection", return_value=("", {}, None)
            ),
            patch.object(type(self.report), "_payload", return_value=self.payload()),
        ):
            wizard.action_refresh()
            with self.assertRaises(UserError):
                wizard.action_submit()
        self.assertEqual(self.report.submission_ids, first)

    def test_same_payable_correction_reuses_bill(self):
        self.report.with_context(_vero_internal=INTERNAL).write(
            {"due_date": "2026-05-12"}
        )
        first = self.attempt()
        first._sync_bill()
        bill = first.bill_id
        correction = self.attempt(self.payload(120, 40))
        with patch.object(
            type(self.backend),
            "_call",
            side_effect=AssertionError("Bill actions must not send returns"),
        ):
            correction.action_retry_bill()
        self.assertEqual(correction.bill_id, bill)
        self.assertEqual(bill.state, "draft")
        self.assertEqual(bill.amount_total, 80)
        self.assertEqual(self.period.payment_move_id, bill)

    def test_old_submission_cannot_restore_superseded_bill(self):
        self.report.with_context(_vero_internal=INTERNAL).write(
            {"due_date": "2026-05-12"}
        )
        first = self.attempt()
        first._sync_bill()
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        with self.assertRaises(UserError):
            first.action_retry_bill()
        with self.assertRaises(UserError):
            first.action_prepare_bill_adjustment()
        self.assertEqual(self.period.payment_move_id, correction.bill_id)
        self.assertEqual(first.bill_id.state, "cancel")
        self.assertEqual(correction.bill_id.amount_total, 180)

    def test_existing_manual_credit_blocks_duplicate_adjustment(self):
        self.report.with_context(_vero_internal=INTERNAL).write(
            {"due_date": "2026-05-12"}
        )
        first = self.attempt()
        first._sync_bill()
        first.bill_id.action_post()
        manual_credit = first.bill_id._reverse_moves(cancel=False)
        correction = self.attempt(self.payload(200, 20))
        with self.assertRaises(UserError):
            correction.action_prepare_bill_adjustment()
        self.assertEqual(first.bill_id.reversal_move_ids, manual_credit)
        self.assertFalse(correction.bill_id)
        self.assertFalse(correction.credit_note_id)
        self.assertEqual(first.bill_id.state, "posted")

    def test_readonly_cannot_process_submission_or_resolve(self):
        attempt = self.attempt()
        attempt._update(state="uncertain", receipt=False)
        for action in (
            "action_retry_bill",
            "action_prepare_bill_adjustment",
            "action_resolve",
            "action_open_bill",
        ):
            with self.subTest(action=action), self.assertRaises(AccessError):
                getattr(attempt.with_user(self.reader), action)()
        resolution = (
            self.env["vero.api.resolution"]
            .with_user(self.user)
            .create(
                {
                    "submission_id": attempt.id,
                    "result": "not_received",
                    "note": "Verified not received",
                }
            )
        )
        with self.assertRaises(AccessError):
            resolution.with_user(self.reader).action_confirm()
        self.assertEqual(attempt.state, "uncertain")
        with self.assertRaises(AccessError):
            self.env["vero.api.wizard"].with_user(self.reader).create(
                {"report_id": self.report.id}
            )

    def test_rpc_context_cannot_unlock_history(self):
        attempt = self.attempt()
        # RPC callers can supply context values, but cannot supply the private
        # Python sentinel that the module uses for its own audited writes.
        for supplied_value in (True, "INTERNAL", 1):
            with self.subTest(value=supplied_value), self.assertRaises(AccessError):
                attempt.with_context(_vero_internal=supplied_value).write(
                    {"snapshot": self.payload(1000, 0), "receipt": "forged"}
                )
        with self.assertRaises(AccessError):
            attempt.unlink()
        with self.assertRaises(AccessError):
            self.report.with_user(self.user).unlink()
        self.assertEqual(attempt.snapshot, self.payload())
        self.assertEqual(attempt.receipt, "unit-test-receipt")

    def test_other_company_history_and_actions_are_denied(self):
        other = self.env["res.company"].create(
            {"name": "Vero isolated history company"}
        )
        backend = self.env["vero.api.backend"].create(
            {
                "name": "Other history connection",
                "company_id": other.id,
                "environment": "sandbox",
                "contact_name": "Other",
                "contact_phone": "+3581",
            }
        )
        range_type = (
            self.env["date.range.type"]
            .with_company(other)
            .create({"name": "Other company months"})
        )
        date_range = (
            self.env["date.range"]
            .with_company(other)
            .create(
                {
                    "name": "Other March 2026",
                    "type_id": range_type.id,
                    "company_id": other.id,
                    "date_start": "2026-03-01",
                    "date_end": "2026-03-31",
                }
            )
        )
        period = self.env["account.vat.period"].create({"date_range_id": date_range.id})
        report = (
            self.env["vero.api.report"]
            .with_context(_vero_internal=INTERNAL)
            .create(
                {
                    "company_id": other.id,
                    "backend_id": backend.id,
                    "vat_period_id": period.id,
                    "kind": "vat",
                    "date_start": "2026-03-01",
                    "date_end": "2026-03-31",
                }
            )
        )
        attempt = (
            self.env["vero.api.submission"]
            .with_context(_vero_internal=INTERNAL)
            .create(
                {
                    "report_id": report.id,
                    "requested_by_id": self.env.uid,
                    "environment": "sandbox",
                    "snapshot": self.payload(),
                    "request_body": self.payload(),
                    "content_hash": p.digest(self.payload()),
                    "state": "uncertain",
                }
            )
        )
        for record in (backend, report, attempt):
            restricted = record.with_user(self.user).with_context(
                allowed_company_ids=self.company.ids
            )
            with self.subTest(model=record._name), self.assertRaises(AccessError):
                restricted.read()
            self.assertFalse(restricted.search([("id", "=", record.id)]))
        with self.assertRaises(AccessError):
            report.with_user(self.user).action_status()
        with self.assertRaises(AccessError):
            attempt.with_user(self.user).action_resolve()
        with self.assertRaises(AccessError):
            self.env["vero.api.wizard"].with_user(self.user).create(
                {"report_id": report.id}
            )

    def test_preflight_rejects_wrong_period_and_existing_external_return(self):
        attempt = self.attempt()
        info = {
            "Period": "2026-03-31",
            "StartDate": "2026-03-01",
            "EndDate": "2026-03-31",
            "Status": "Missing",
            "DueDate": "2026-05-12",
        }
        responses = [
            (503, {"ErrorText": "Temporarily unavailable"}),
            (200, []),
            (200, {"FilingPeriod": []}),
            (200, {"FilingPeriod": [dict(info, StartDate="2026-01-01")]}),
            (200, {"FilingPeriod": [info, info]}),
            (200, {"FilingPeriod": [dict(info, Status="Expired")]}),
            (200, {"FilingPeriod": [dict(info, Status="Processed")]}),
        ]
        with patch.object(
            type(self.backend), "_connection", return_value=("", {}, None)
        ):
            for response in responses:
                with (
                    self.subTest(response=response),
                    patch.object(
                        type(self.backend), "_call", return_value=response
                    ) as transport,
                    self.assertRaises(UserError),
                ):
                    attempt._preflight()
                transport.assert_called_once_with(
                    "GetVATPeriods/v1", {"BusinessId": "9999999-2", "FilingYear": 2026}
                )
            self.assertFalse(self.report.due_date)
            with patch.object(
                type(self.backend),
                "_call",
                return_value=(200, {"FilingPeriod": [info]}),
            ):
                attempt._preflight()
        self.assertEqual(self.report.due_date, date(2026, 5, 12))

    def test_access_revocation_blocks_queued_preflight_before_network(self):
        attempt = self.attempt()
        attempt._update(state="queued", receipt=False)
        self.user.groups_id = [
            Command.set(self.env.ref("account.group_account_readonly").ids)
        ]
        with (
            patch.object(type(self.backend), "_call") as transport,
            self.assertRaises(AccessError),
        ):
            attempt._preflight()
        transport.assert_not_called()
        self.assertEqual(attempt.with_env(self.env).state, "queued")

    def test_disabled_connection_blocks_preflight_before_network(self):
        attempt = self.attempt()
        self.backend.active = False
        with (
            patch.object(type(self.backend), "_call") as transport,
            self.assertRaises(UserError),
        ):
            attempt._preflight()
        transport.assert_not_called()

    def test_transport_does_not_follow_redirects_or_retry_errors(self):
        root = "https://api-sandbox.vero.fi/Return/SAT"
        headers = {"Ocp-Apim-Subscription-Key": "unit-test-key"}
        for status in (302, 401, 429, 503):
            response = Mock(status_code=status)
            response.json.side_effect = ValueError("An HTML error or redirect page")
            with (
                self.subTest(status=status),
                patch.object(
                    type(self.backend),
                    "_connection",
                    return_value=(root, headers, None),
                ),
                patch.object(
                    vero_backend.requests, "post", return_value=response
                ) as post,
            ):
                code, body = self.backend.with_user(self.user)._call(
                    "FileVATReturn/v2", self.payload()
                )
            self.assertEqual(code, status)
            self.assertEqual(body, {"ErrorText": "The service did not return JSON."})
            post.assert_called_once_with(
                root + "/FileVATReturn/v2",
                json=self.payload(),
                headers=headers,
                cert=None,
                timeout=(10, 45),
                allow_redirects=False,
            )
        with (
            patch.object(
                type(self.backend), "_connection", return_value=(root, headers, None)
            ),
            patch.object(
                vero_backend.requests,
                "post",
                side_effect=requests.Timeout("Simulated timeout"),
            ) as post,
            self.assertRaises(requests.Timeout),
        ):
            self.backend.with_user(self.user)._call("FileVATReturn/v2", self.payload())
        post.assert_called_once()

    def test_failed_status_query_preserves_receipt_and_last_successful_query(self):
        attempt = self.attempt()
        self.report.with_context(_vero_internal=INTERNAL).write(
            {
                "last_query": {"http_status": 200, "body": {"Status": "Processed"}},
                "remote_status": "Processed",
            }
        )
        with (
            patch.object(
                type(self.backend),
                "_call",
                side_effect=requests.Timeout("Simulated timeout"),
            ),
            self.assertRaises(UserError),
        ):
            self.report.with_user(self.user).action_fetch_status()
        self.assertEqual(attempt.state, "accepted")
        self.assertEqual(attempt.receipt, "unit-test-receipt")
        self.assertEqual(self.report.remote_status, "Processed")
        self.assertEqual(self.report.last_query["http_status"], 200)
        with patch.object(
            type(self.backend),
            "_call",
            return_value=(503, {"ErrorText": "Unavailable"}),
        ):
            self.report.with_user(self.user).action_fetch_status()
        self.assertEqual(self.report.last_query["http_status"], 503)
        self.assertEqual(attempt.state, "accepted")
        self.assertTrue(self.period.vero_vat_received)

    def test_invalid_mis_values_and_nonzero_no_activity_are_rejected(self):
        for invalid in (None, True, "not a number", float("nan"), float("inf")):
            values = dict.fromkeys(p.VAT_MAPPING, 0)
            values["vero_25_5"] = invalid
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                p.vat_payload(
                    values, "9999999-2", "2026-03-31", p.contact("Test", "+3581")
                )
        values = dict.fromkeys(p.VAT_MAPPING, 0)
        values["tavaroiden_myynnit_muihin_eu_maihin"] = 100
        with self.assertRaises(ValueError):
            p.vat_payload(
                values, "9999999-2", "2026-03-31", p.contact("Test", "+3581"), True
            )

    def test_ec_uses_commercial_partner_and_only_posted_month(self):
        # A February tax lock in a development database would make Odoo move
        # the February fixture into March, invalidating the boundary check.
        self.company.tax_lock_date = False
        goods, services = self.env["account.account.tag"].create(
            [
                {"name": "EC scope goods", "applicability": "taxes"},
                {"name": "EC scope services", "applicability": "taxes"},
            ]
        )
        self.backend.write(
            {
                "goods_tag_ids": [Command.set(goods.ids)],
                "services_tag_ids": [Command.set(services.ids)],
            }
        )
        commercial = (
            self.env["res.partner"]
            .with_context(no_vat_validation=True)
            .create(
                {
                    "name": "EC commercial buyer",
                    "is_company": True,
                    "vat": "SE123456789001",
                }
            )
        )
        contact = (
            self.env["res.partner"]
            .with_context(no_vat_validation=True)
            .create(
                {
                    "name": "Delivery address",
                    "parent_id": commercial.id,
                    "type": "delivery",
                }
            )
        )
        account = self.env["account.account"].search(
            [("company_ids", "in", self.company.id), ("account_type", "=", "income")],
            limit=1,
        )
        journal = self.env["account.journal"].search(
            [("company_id", "=", self.company.id), ("type", "=", "general")], limit=1
        )
        moves = self.env["account.move"]
        for day, amount, partner, tags, posted in (
            ("2026-03-01", 100, contact, goods, True),
            ("2026-03-31", 40, commercial, services, True),
            ("2026-03-15", 700, commercial, goods, False),
            ("2026-02-28", 800, commercial, goods, True),
            ("2026-04-01", 900, commercial, goods, True),
        ):
            move = self.env["account.move"].create(
                {
                    "journal_id": journal.id,
                    "date": day,
                    "line_ids": [
                        Command.create(
                            {
                                "name": "EC scope sale",
                                "account_id": account.id,
                                "partner_id": partner.id,
                                "credit": amount,
                                "tax_tag_ids": [Command.set(tags.ids)],
                            }
                        ),
                        Command.create(
                            {
                                "name": "Balance",
                                "account_id": self.company.vat_account_id.id,
                                "debit": amount,
                            }
                        ),
                    ],
                }
            )
            if posted:
                move.action_post()
            self.assertEqual(move.date, date.fromisoformat(day))
            moves |= move
        rows = self.report.with_user(self.user)._ec_buyers()
        self.assertEqual(
            rows,
            [
                {
                    "CountryCode": "SE",
                    "VATIdentifier": "123456789001",
                    "SalesOfGoods": 100,
                    "SalesOfServices": 40,
                    "TriangulationSales": 0,
                }
            ],
        )
        self.assertEqual(len(moves.filtered(lambda move: move.state == "draft")), 1)

    def test_connection_url_can_be_completed_before_first_submission(self):
        # A preview is possible without network credentials or the final URL.
        # Opening it must not make subsequent connection setup impossible.
        self.backend.with_user(self.user).write(
            {"api_root": "https://api-sandbox.vero.fi/Return/SAT"}
        )
        self.assertEqual(
            self.backend.api_root, "https://api-sandbox.vero.fi/Return/SAT"
        )
        self.attempt()
        with self.assertRaises(UserError):
            self.backend.with_user(self.user).write(
                {"api_root": "https://api-sandbox.vero.fi/another-path"}
            )

    def test_connection_url_can_be_fixed_after_failed_attempt(self):
        attempt = self.attempt()
        for state, root in (
            ("error", "https://api-sandbox.vero.fi/Return/SAT"),
            ("not_received", "https://api-sandbox.vero.fi/Return/SAT/"),
        ):
            with self.subTest(state=state):
                attempt._update(state=state, receipt=False)
                self.backend.with_user(self.user).write({"api_root": root})
                self.assertEqual(self.backend.api_root, root)

    def test_connection_url_is_frozen_during_pending_or_uncertain_attempt(self):
        attempt = self.attempt()
        for state in ("queued", "sending", "uncertain"):
            attempt._update(state=state, receipt=False)
            with self.subTest(state=state), self.assertRaises(UserError):
                self.backend.with_user(self.user).write(
                    {"api_root": "https://api-sandbox.vero.fi/Return/SAT"}
                )

    def test_failed_correction_does_not_unlock_received_connection(self):
        self.attempt()
        failed_correction = self.attempt(self.payload(200, 20))
        failed_correction._update(state="error", receipt=False)
        with self.assertRaises(UserError):
            self.backend.with_user(self.user).write(
                {"api_root": "https://api-sandbox.vero.fi/Return/SAT"}
            )

    def test_multiple_environments_require_explicit_selection(self):
        single = self.period.with_user(self.user).action_do_send()
        self.assertEqual(
            self.env["vero.api.wizard"].browse(single["res_id"]).backend_id,
            self.backend,
        )
        self.env["vero.api.backend"].create(
            {
                "name": "Explicit production selection",
                "company_id": self.company.id,
                "environment": "production",
                "contact_name": "Test",
                "contact_phone": "+3581",
            }
        )
        for action in ("action_do_send", "action_do_cancel_send", "action_vero_ec"):
            with self.subTest(action=action):
                result = getattr(self.period.with_user(self.user), action)()
                self.assertFalse(
                    self.env["vero.api.wizard"].browse(result["res_id"]).backend_id
                )

    def test_real_invoice_and_refund_reach_mis_payload_in_their_period(self):
        template = self.company.mis_report_instance_id
        original_dates = (template.date_from, template.date_to, template.target_move)
        baseline = self.report.with_user(self.user)._payload()
        source_tax = self.env["account.tax"].search(
            [
                ("company_id", "=", self.company.id),
                ("type_tax_use", "=", "sale"),
                ("amount_type", "=", "percent"),
                ("amount", "=", 25.5),
                ("price_include", "=", False),
            ],
            limit=1,
        )
        self.assertTrue(
            source_tax, "The Finnish test chart must have a 25.5% sales tax"
        )
        tax = source_tax.copy({"name": "Vero regression 25.5%"})
        # The installed Finnish MIS template reads fi_320 for the high rate.
        # Configure this isolated fixture explicitly rather than relying on
        # unrelated custom tax mappings in a database used for development.
        tags = self.env["account.account.tag"].search(
            [("name", "in", ["+fi_320", "-fi_320"]), ("applicability", "=", "taxes")]
        )
        for name in ("+fi_320", "-fi_320"):
            if not tags.filtered(lambda tag, name=name: tag.name == name):
                tags |= self.env["account.account.tag"].create(
                    {"name": name, "applicability": "taxes"}
                )
        tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == "tax"
        ).write(
            {
                "tag_ids": [
                    Command.set(tags.filtered(lambda tag: tag.name == "+fi_320").ids)
                ]
            }
        )
        tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == "tax"
        ).write(
            {
                "tag_ids": [
                    Command.set(tags.filtered(lambda tag: tag.name == "-fi_320").ids)
                ]
            }
        )
        account = self.env["account.account"].search(
            [("company_ids", "in", self.company.id), ("account_type", "=", "income")],
            limit=1,
        )
        customer = self.env["res.partner"].create(
            {"name": "Domestic VAT regression customer"}
        )
        posted = self.env["account.move"]
        for kind, day, amount, should_post in (
            ("out_invoice", "2026-03-15", 1000, True),
            ("out_refund", "2026-03-20", 200, True),
            ("out_invoice", "2026-03-25", 700, False),
            ("out_invoice", "2026-04-01", 900, True),
        ):
            move = self.env["account.move"].create(
                {
                    "move_type": kind,
                    "partner_id": customer.id,
                    "company_id": self.company.id,
                    "invoice_date": day,
                    "date": day,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": "Taxed test service",
                                "account_id": account.id,
                                "quantity": 1,
                                "price_unit": amount,
                                "tax_ids": [Command.set(tax.ids)],
                            }
                        )
                    ],
                }
            )
            if should_post:
                move.action_post()
                posted |= move
        self.assertEqual(
            posted.filtered(lambda move: move.move_type == "out_refund").amount_tax, 51
        )
        # A user's temporary analytical filter must not filter the tax return.
        body = (
            self.report.with_user(self.user)
            .with_context(mis_analytic_domain=[("id", "=", 0)])
            ._payload()
        )
        before = baseline["VATDetails"]["VATOnDomesticSalesByTaxRate"]["HighVATRate"]
        self.assertAlmostEqual(
            body["VATDetails"]["VATOnDomesticSalesByTaxRate"]["HighVATRate"] - before,
            204,
            places=2,
        )
        self.assertAlmostEqual(p.payable(body) - p.payable(baseline), 204, places=2)
        self.assertEqual(body["FilingPeriod"], "2026-03-31")
        self.assertEqual(
            body["VATDetails"]["DeductibleVAT"], baseline["VATDetails"]["DeductibleVAT"]
        )
        self.assertEqual(
            (template.date_from, template.date_to, template.target_move), original_dates
        )

    def test_mis_temporary_instance_cleanup_and_caller_privileges(self):
        instances = self.env["mis.report.instance"]
        original_count = instances.search_count([])
        template = self.company.mis_report_instance_id
        original_name = template.name
        created_ids = []

        def fail_computation(instance):
            created_ids.append(instance.id)
            self.assertEqual(instance.env.uid, self.user.id)
            self.assertFalse(
                instance.env.su,
                "Tax calculation must retain the accountant record rules",
            )
            self.assertEqual(instance.company_id, self.company)
            self.assertEqual(instance.env.companies, self.company)
            self.assertTrue(instance.temporary)
            self.assertEqual(instance.target_move, "posted")
            self.assertFalse(
                any(key.startswith("default_") for key in instance.env.context)
            )
            self.assertNotEqual(instance.name, "Injected report name")
            raise UserError(_("Simulated MIS calculation error"))

        report = self.report.with_user(self.user).with_context(
            default_name="Injected report name",
            default_temporary=False,
            default_target_move="all",
            default_company_id=0,
        )
        with (
            patch.object(MisReportInstance, "_compute_matrix", new=fail_computation),
            self.assertRaisesRegex(UserError, "Simulated MIS calculation error"),
        ):
            report._mis_values()
        self.assertEqual(len(created_ids), 1)
        self.assertFalse(instances.browse(created_ids).exists())
        self.assertEqual(instances.search_count([]), original_count)
        self.assertEqual(template.name, original_name)
