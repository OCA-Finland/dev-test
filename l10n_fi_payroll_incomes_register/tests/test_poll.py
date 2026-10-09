# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from lxml import etree
from psycopg2 import IntegrityError

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tools import mute_logger

# pylint: disable=odoo-addons-relative-import
from odoo.addons.queue_job.tests.common import trap_jobs

from ..tools.ir_client import IrCallError, IrCallResult
from .common import IncomesRegisterCommon

PERIOD_FROM = date(2025, 5, 1)
PERIOD_TO = date(2025, 5, 31)
PAYMENT_DATE = date(2025, 5, 25)


class TestIrPoll(IncomesRegisterCommon):
    """Poll delivery status and keep a locked payslip from being reopened."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.company_registry = "1234567-8"
        cls.company.l10n_fi_payroll_ir_contact_person_id = cls.env[
            "res.partner"
        ].create(
            {
                "name": "Test Contact",
                "phone": "+358401234567",
                "email": "contact@example.com",
            }
        )
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)],
            limit=1,
        )
        if not cls.journal:
            cls.journal = cls.env["account.journal"].create(
                {
                    "name": "Miscellaneous",
                    "code": "MISC",
                    "type": "general",
                    "company_id": cls.company.id,
                }
            )
        cls.employee = cls.env["hr.employee"].create(
            {"name": "Poll Employee", "ssnid": "010101-123A"}
        )
        cls.contract = cls.env["hr.contract"].create(
            {
                "name": "Poll Contract",
                "employee_id": cls.employee.id,
                "wage": 1000.0,
                "state": "open",
                "date_start": date(2025, 1, 1),
                "journal_id": cls.journal.id,
            }
        )
        cls.rule = cls.env["hr.salary.rule"].create(
            {"name": "Reportable wage", "code": "201", "appears_on_payslip": True}
        )
        cls.backend = cls.backend_model.create(
            IncomesRegisterCommon.backend_vals(cls, material=cls.material)
        )
        cls.backend.state = "confirmed"

    def _done_payslip(self, name):
        """Create one done payslip with a reportable line.

        :param str name: payslip name
        :return: done payslip
        :rtype: hr.payslip
        """
        payslip = self.env["hr.payslip"].create(
            {
                "name": name,
                "employee_id": self.employee.id,
                "contract_id": self.contract.id,
                "date_from": PERIOD_FROM,
                "date_to": PERIOD_TO,
                "payment_date": PAYMENT_DATE,
            }
        )
        self.env["hr.payslip.line"].create(
            {
                "name": "Reportable wage",
                "code": "201",
                "slip_id": payslip.id,
                "salary_rule_id": self.rule.id,
                "employee_id": payslip.employee_id.id,
                "contract_id": payslip.contract_id.id,
                "appears_on_payslip": True,
                "amount": 100.0,
            }
        )
        payslip.state = "done"
        return payslip

    def _queue(self, payslips):
        """Queue a delivery and do not run its send job.

        :param hr.payslip payslips: payslips to send
        :return: queued submissions
        :rtype: l10n_fi.ir.submission
        """
        action = payslips.action_open_ir_send_wizard()
        wizard = (
            self.env["l10n_fi.ir.send.wizard"]
            .with_context(**action["context"])
            .create({})
        )
        with trap_jobs():
            wizard.action_confirm()
        return self.env["l10n_fi.ir.submission"].search(
            [("line_ids.payslip_id", "in", payslips.ids)]
        )

    def _receive(self, submission):
        """Pretend the acknowledgement has been accepted.

        :param l10n_fi.ir.submission submission: queued delivery
        :return: the same delivery, now received
        :rtype: l10n_fi.ir.submission
        """
        submission.write(
            {
                "state": "received",
                "sent_at": fields.Datetime.now(),
                "next_poll_at": fields.Datetime.now() - timedelta(minutes=1),
                "ir_delivery_id": "B" * 32,
            }
        )
        return submission

    def _status_result(self, status, invalid=None, errors=None):
        """Build a status result the patched client can return.

        :param int status: DeliveryDataStatus
        :param list invalid: ``(item id, code, message)`` for rejected reports
        :param list errors: ``(code, message)`` for the whole delivery
        :return: verified result
        :rtype: IrCallResult
        """
        response = etree.Element("StatusResponse")
        etree.SubElement(response, "DeliveryDataStatus").text = str(status)
        etree.SubElement(response, "IRDeliveryId").text = "C" * 32
        if invalid:
            container = etree.SubElement(response, "InvalidItems")
            for item_id, code, message in invalid:
                item = etree.SubElement(container, "Item")
                etree.SubElement(item, "ItemId").text = item_id
                item_errors = etree.SubElement(item, "ItemErrors")
                info = etree.SubElement(item_errors, "ErrorInfo")
                etree.SubElement(info, "ErrorCode").text = code
                etree.SubElement(info, "ErrorMessage").text = message
        if errors:
            container = etree.SubElement(response, "DeliveryErrors")
            for code, message in errors:
                info = etree.SubElement(container, "ErrorInfo")
                etree.SubElement(info, "ErrorCode").text = code
                etree.SubElement(info, "ErrorMessage").text = message
        root = etree.Element("StatusResponseFromIR")
        root.append(response)
        return IrCallResult(200, root, etree.tostring(root))

    def _poll(self, submission, result=None, error=None):
        """Run one poll with the HTTP call replaced.

        :param l10n_fi.ir.submission submission: delivery to poll
        :param IrCallResult result: answer to return
        :param Exception error: error to raise from the call
        :return: ``None``
        :rtype: None
        """

        def fake_post(**_kwargs):
            if error:
                raise error
            return result

        with patch(
            "odoo.addons.l10n_fi_payroll_incomes_register.models"
            ".ir_submission.post_signed",
            side_effect=fake_post,
        ) as post:
            submission._job_poll()
            self._post = post
        self.env.invalidate_all()

    def test_processed_status_validates_every_line(self):
        """Status 3 with no invalid items validates the delivery and keeps the lock."""
        payslip = self._done_payslip("Valid")
        submission = self._receive(self._queue(payslip))
        self._poll(submission, result=self._status_result(3))
        document = self._post.call_args.kwargs["document"]
        self.assertEqual(document.find("DeliveryId").text, submission.delivery_id)
        self.assertEqual(document.find("IRDeliveryId").text, "B" * 32)
        parsed = etree.fromstring(etree.tostring(document))
        self.assertIsNone(parsed.find("Source"))
        schema_path = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "wsdl"
            / "StatusRequestToIR.xsd"
        )
        schema = etree.XMLSchema(etree.parse(str(schema_path)))
        schema.assertValid(parsed)
        self.assertEqual(submission.state, "valid")
        self.assertEqual(submission.line_ids.state, "valid")
        self.assertTrue(submission.line_ids.payslip_locked)
        self.assertEqual(payslip.l10n_fi_ir_state, "valid")
        self.assertFalse(submission.next_poll_at)

    def test_processed_status_can_reject_one_report(self):
        """Status 3 rejects only the reports listed as invalid."""
        first = self._done_payslip("Kept")
        second = self._done_payslip("Dropped")
        submission = self._receive(self._queue(first | second))
        rejected_ref = submission.line_ids.filtered(
            lambda line: line.payslip_id == second
        ).report_ref
        self._poll(
            submission,
            result=self._status_result(
                3, invalid=[(rejected_ref, "ERR", "Report rejected")]
            ),
        )
        self.assertEqual(submission.state, "partially_rejected")
        kept = submission.line_ids.filtered(lambda line: line.payslip_id == first)
        dropped = submission.line_ids.filtered(lambda line: line.payslip_id == second)
        self.assertEqual(kept.state, "valid")
        self.assertTrue(kept.payslip_locked)
        self.assertEqual(dropped.state, "rejected")
        self.assertFalse(dropped.payslip_locked)
        self.assertIn("ERR", dropped.error_message)
        self.assertEqual(first.l10n_fi_ir_state, "valid")
        self.assertEqual(second.l10n_fi_ir_state, "rejected")

    def test_status_4_and_5_reject_the_delivery(self):
        """Status 4 and 5 reject every report and release the payslips."""
        for status in (4, 5):
            payslip = self._done_payslip(f"Status {status}")
            submission = self._receive(self._queue(payslip))
            self._poll(
                submission,
                result=self._status_result(status, errors=[("REJ", "Rejected")]),
            )
            self.assertEqual(submission.state, "rejected")
            self.assertIn("REJ", submission.error_message)
            self.assertEqual(submission.line_ids.state, "rejected")
            self.assertFalse(submission.line_ids.payslip_locked)
            self.assertEqual(payslip.l10n_fi_ir_state, "rejected")

    def test_processing_status_waits_longer_each_time(self):
        """A delivery that is still processing is polled at 5, then 15 minutes."""
        payslip = self._done_payslip("Waiting")
        submission = self._receive(self._queue(payslip))
        self._poll(submission, result=self._status_result(2))
        self.assertEqual(submission.state, "received")
        self.assertEqual(submission.poll_count, 1)
        first_gap = submission.next_poll_at - fields.Datetime.now()
        self.assertGreater(first_gap, timedelta(minutes=4))
        self.assertLess(first_gap, timedelta(minutes=6))
        self._poll(submission, result=self._status_result(2))
        self.assertEqual(submission.poll_count, 2)
        second_gap = submission.next_poll_at - fields.Datetime.now()
        self.assertGreater(second_gap, timedelta(minutes=14))
        self.assertLess(second_gap, timedelta(minutes=16))
        self._poll(submission, result=self._status_result(2))
        self.assertEqual(submission.poll_count, 3)
        third_gap = submission.next_poll_at - fields.Datetime.now()
        self.assertGreater(third_gap, timedelta(minutes=59))
        self.assertLess(third_gap, timedelta(minutes=61))

    def test_poll_stops_at_the_hour_limit(self):
        """Automatic polling stops without a call once the limit has passed."""
        payslip = self._done_payslip("Old")
        submission = self._receive(self._queue(payslip))
        submission.sent_at = fields.Datetime.now() - timedelta(hours=49)
        self._poll(submission, result=self._status_result(2))
        self._post.assert_not_called()
        self.assertEqual(submission.state, "needs_check")
        self.assertFalse(submission.next_poll_at)

    def test_check_status_zero_marks_not_received_and_resend_keeps_the_id(self):
        """Status 0 closes the delivery, and resend uses the same DeliveryId."""
        payslip = self._done_payslip("Missing")
        submission = self._receive(self._queue(payslip))
        delivery_id = submission.delivery_id
        submission.state = "uncertain"
        with patch(
            "odoo.addons.l10n_fi_payroll_incomes_register.models"
            ".ir_submission.post_signed",
            return_value=self._status_result(0),
        ):
            submission.action_check_status()
        self.env.invalidate_all()
        self.assertEqual(submission.state, "not_received")
        self.assertFalse(submission.line_ids.payslip_locked)
        self.assertEqual(payslip.l10n_fi_ir_state, "not_sent")
        with trap_jobs() as trap:
            submission.action_resend()
        self.assertEqual(submission.state, "queued")
        self.assertEqual(submission.delivery_id, delivery_id)
        self.assertTrue(submission.line_ids.payslip_locked)
        trap.assert_jobs_count(1)
        self.assertEqual(trap.calls[0].properties["max_retries"], 1)

    def test_mark_not_received_posts_the_note(self):
        """A manager's note is required and is posted on the delivery."""
        payslip = self._done_payslip("Note")
        submission = self._receive(self._queue(payslip))
        submission.state = "needs_check"
        wizard = self.env["l10n_fi.ir.not.received.wizard"].create(
            {"submission_id": submission.id, "note": "   "}
        )
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.note = "Nothing in the e-service."
        wizard.action_confirm()
        self.assertEqual(submission.state, "not_received")
        notes = " ".join(submission.message_ids.mapped("body"))
        self.assertIn("Nothing in the e-service.", notes)

    def test_poll_failure_is_raised_for_the_queue(self):
        """A failed status call stays received so the queue can retry it."""
        payslip = self._done_payslip("Retry")
        submission = self._receive(self._queue(payslip))
        with self.assertRaises(IrCallError):
            self._poll(
                submission,
                error=IrCallError("uncertain", "The connection timed out."),
            )
        self.assertEqual(submission.state, "received")
        function = self.env["queue.job.function"].search(
            [
                ("method", "=", "_job_poll"),
                ("model_id.model", "=", "l10n_fi.ir.submission"),
            ]
        )
        self.assertTrue(function.retry_pattern)

    def test_cron_sweeps_sending_and_enqueues_due_polls(self):
        """Sending rows older than 15 minutes become uncertain, and due polls queue."""
        stalled_slip = self._done_payslip("Stalled")
        stalled = self._queue(stalled_slip)
        stalled.write(
            {
                "state": "sending",
                "sent_at": fields.Datetime.now() - timedelta(minutes=20),
            }
        )
        fresh_slip = self._done_payslip("Fresh")
        fresh = self._queue(fresh_slip)
        fresh.write({"state": "sending", "sent_at": fields.Datetime.now()})
        due_slip = self._done_payslip("Due")
        due = self._receive(self._queue(due_slip))
        with trap_jobs() as trap:
            self.env["l10n_fi.ir.submission"]._cron_poll()
        self.assertEqual(stalled.state, "uncertain")
        self.assertEqual(fresh.state, "sending")
        due_calls = [
            call
            for call in trap.calls
            if call.properties.get("identity_key") == f"l10n_fi_ir_poll_{due.id}"
        ]
        self.assertEqual(len(due_calls), 1)

    def test_locked_payslip_cannot_be_reopened_or_deleted(self):
        """Draft, cancel, and delete are blocked. A refund warns and still runs."""
        payslip = self._done_payslip("Locked")
        self._queue(payslip)
        self.assertTrue(payslip.l10n_fi_ir_line_ids.payslip_locked)
        with self.assertRaises(UserError):
            payslip.action_payslip_draft()
        with self.assertRaises(UserError):
            payslip.action_payslip_cancel()
        with self.assertRaises(UserError):
            payslip.unlink()
        self.assertTrue(payslip.exists())
        action = payslip.refund_sheet()
        self.assertEqual(action["res_model"], "hr.payslip")
        notes = " ".join(payslip.message_ids.mapped("body"))
        self.assertIn("Correct the earnings report manually.", notes)

    def test_unique_index_blocks_a_second_lock(self):
        """Two open deliveries cannot lock the same payslip."""
        payslip = self._done_payslip("Twice")
        self._queue(payslip)
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self.env["l10n_fi.ir.submission"].create(
                    {
                        "backend_id": self.backend.id,
                        "environment": "test",
                        "delivery_id": "second-delivery",
                        "payment_date": PAYMENT_DATE,
                        "date_from": PERIOD_FROM,
                        "date_to": PERIOD_TO,
                        "line_ids": [
                            Command.create(
                                {
                                    "payslip_id": payslip.id,
                                    "report_ref": payslip.l10n_fi_ir_report_ref,
                                }
                            )
                        ],
                    }
                )
