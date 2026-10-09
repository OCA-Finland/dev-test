# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

from lxml import etree

from odoo import Command
from odoo.exceptions import UserError
from odoo.modules.module import get_module_path

# pylint: disable=odoo-addons-relative-import
from odoo.addons.queue_job.tests.common import trap_jobs

from ..tools.ir_client import IrCallError, IrCallResult
from .common import IncomesRegisterCommon

PERIOD_FROM = date(2025, 5, 1)
PERIOD_TO = date(2025, 5, 31)
PAYMENT_DATE = date(2025, 5, 25)


class TestIrSend(IncomesRegisterCommon):
    """Queue earnings reports and record what SendWageReports answered."""

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
            {"name": "Test Employee", "ssnid": "010101-123A"}
        )
        cls.contract = cls.env["hr.contract"].create(
            {
                "name": "Test Contract",
                "employee_id": cls.employee.id,
                "wage": 1000.0,
                "state": "open",
                "date_start": date(2025, 1, 1),
                "journal_id": cls.journal.id,
            }
        )
        cls.rule = cls.env["hr.salary.rule"].create(
            {
                "name": "Reportable wage",
                "code": "201",
                "appears_on_payslip": True,
            }
        )
        cls.backend = cls.backend_model.create(
            IncomesRegisterCommon.backend_vals(cls, material=cls.material)
        )
        cls.backend.state = "confirmed"

    def _payslip_vals(self, name, **extra):
        """Return create values for one done-ready payslip.

        :param str name: payslip name
        :param dict extra: values that replace the defaults
        :return: create values
        :rtype: dict
        """
        values = {
            "name": name,
            "employee_id": self.employee.id,
            "contract_id": self.contract.id,
            "date_from": PERIOD_FROM,
            "date_to": PERIOD_TO,
            "payment_date": PAYMENT_DATE,
        }
        values.update(extra)
        return values

    def _add_line(self, payslip):
        """Add one reportable wage line.

        :param hr.payslip payslip: payslip that must be reportable
        :return: created line
        :rtype: hr.payslip.line
        """
        return self.env["hr.payslip.line"].create(self._line_vals(payslip))

    def _line_vals(self, payslip):
        """Return create values for one reportable line.

        :param hr.payslip payslip: payslip the line belongs to
        :return: create values
        :rtype: dict
        """
        return {
            "name": "Reportable wage",
            "code": "201",
            "slip_id": payslip.id,
            "salary_rule_id": self.rule.id,
            "employee_id": payslip.employee_id.id,
            "contract_id": payslip.contract_id.id,
            "appears_on_payslip": True,
            "amount": 100.0,
        }

    def _done_payslip(self, name="Done payslip"):
        """Create one done payslip with a reportable line.

        :param str name: payslip name
        :return: done payslip
        :rtype: hr.payslip
        """
        payslip = self.env["hr.payslip"].create(self._payslip_vals(name))
        self._add_line(payslip)
        payslip.state = "done"
        return payslip

    def _queue(self, payslips):
        """Open the wizard and confirm, without running the send job.

        :param hr.payslip payslips: payslips to queue
        :return: queued submissions and the trapped job calls
        :rtype: tuple
        """
        action = payslips.action_open_ir_send_wizard()
        wizard = (
            self.env["l10n_fi.ir.send.wizard"]
            .with_context(**action["context"])
            .create({})
        )
        with trap_jobs() as trap:
            wizard.action_confirm()
        submissions = self.env["l10n_fi.ir.submission"].search(
            [("line_ids.payslip_id", "in", payslips.ids)]
        )
        return wizard, submissions, trap

    def _ack(self, status, errors=None):
        """Build a verified acknowledgement result.

        :param int status: DeliveryDataStatus
        :param list errors: optional ``(code, message)`` pairs
        :return: result the patched client returns
        :rtype: IrCallResult
        """
        root = etree.Element("AckFromIR")
        ack = etree.SubElement(root, "AckData")
        etree.SubElement(ack, "DeliveryDataStatus").text = str(status)
        etree.SubElement(ack, "IRDeliveryId").text = "A" * 32
        if errors:
            delivery_errors = etree.SubElement(ack, "DeliveryErrors")
            for code, message in errors:
                info = etree.SubElement(delivery_errors, "ErrorInfo")
                etree.SubElement(info, "ErrorCode").text = code
                etree.SubElement(info, "ErrorMessage").text = message
        return IrCallResult(200, root, etree.tostring(root))

    def _run_send(self, submission, result=None, error=None, check_schema=False):
        """Run the send job with the HTTP call replaced.

        :param l10n_fi.ir.submission submission: queued delivery
        :param IrCallResult result: answer to return
        :param Exception error: error to raise from the call
        :param bool check_schema: validate the signed request against the XSD
        :return: ``None``
        :rtype: None
        """

        def fake_post(**kwargs):
            self.env.cr.execute(
                "SELECT state FROM l10n_fi_ir_submission WHERE id = %s",
                [submission.id],
            )
            self.assertEqual(self.env.cr.fetchone()[0], "sending")
            if check_schema:
                schema_path = (
                    Path(get_module_path("l10n_fi_payroll_community"))
                    / "xsd"
                    / "WageReportsToIR.xsd"
                )
                schema = etree.XMLSchema(etree.parse(str(schema_path)))
                schema.assertValid(kwargs["document"])
            if error:
                raise error
            return result

        # The queued row must be flushed first. invalidate_all() after the job
        # flushes again, and a pending lock write would put the flag back.
        # The job opens its own cursor. In a TransactionCase that cursor is a
        # second connection and cannot see this test's uncommitted row, so the
        # claim finds nothing. Test mode makes that cursor a proxy on this
        # transaction, which is how a committed row looks to the worker.
        self.env.flush_all()
        self.registry.enter_test_mode(self.cr)
        self.addCleanup(self.registry.leave_test_mode)
        with patch(
            "odoo.addons.l10n_fi_payroll_incomes_register.models"
            ".ir_submission.post_signed",
            side_effect=fake_post,
        ):
            submission._job_send()
        self.env.invalidate_all()

    def test_only_done_payslips_are_sent(self):
        """Draft payslips are skipped, and a selection of only drafts is refused."""
        done = self._done_payslip("Done")
        draft = self.env["hr.payslip"].create(self._payslip_vals("Draft"))
        self._add_line(draft)
        with self.assertRaises(UserError):
            draft.action_open_ir_send_wizard()
        action = (done | draft).action_open_ir_send_wizard()
        self.assertEqual(action["context"]["default_payslip_ids"][0][2], done.ids)
        self.assertIn(draft.display_name, action["context"]["default_skipped_message"])
        _wizard, submissions, trap = self._queue(done)
        self.assertEqual(submissions.line_ids.payslip_id, done)
        trap.assert_jobs_count(1)
        self.assertEqual(trap.calls[0].properties["max_retries"], 1)
        self.assertEqual(trap.calls[0].properties["channel"], "root.l10n_fi_ir")

    def test_batch_opens_the_same_wizard(self):
        """A payslip batch sends the done payslips of that batch."""
        done = self._done_payslip("Batch")
        batch = self.env["hr.payslip.run"].create(
            {
                "name": "May",
                "journal_id": self.journal.id,
                "date_start": PERIOD_FROM,
                "date_end": PERIOD_TO,
                "l10n_fi_payment_date": PAYMENT_DATE,
            }
        )
        done.payslip_run_id = batch
        action = batch.action_open_ir_send_wizard()
        self.assertEqual(action["context"]["default_payslip_ids"][0][2], done.ids)

    def test_problems_are_listed_together(self):
        """Company data, lines, dates, and the lock share one error."""
        locked = self._done_payslip("Locked")
        self.env["l10n_fi.ir.submission"].create(
            {
                "backend_id": self.backend.id,
                "environment": "test",
                "delivery_id": str(uuid.uuid4()),
                "payment_date": PAYMENT_DATE,
                "date_from": PERIOD_FROM,
                "date_to": PERIOD_TO,
                "line_ids": [
                    Command.create(
                        {
                            "payslip_id": locked.id,
                            "report_ref": locked._l10n_fi_get_ir_report_ref(),
                        }
                    )
                ],
            }
        )
        broken = self.env["hr.payslip"].create(
            self._payslip_vals("Broken", payment_date=False)
        )
        broken.state = "done"
        self.company.company_registry = False
        self.company.l10n_fi_payroll_ir_contact_person_id = False
        wizard = self.env["l10n_fi.ir.send.wizard"].with_context(
            default_payslip_ids=[(6, 0, (broken | locked).ids)],
            default_environment="test",
        )
        with self.assertRaises(UserError) as caught:
            wizard.default_get(
                [
                    "payslip_ids",
                    "environment",
                    "warning_message",
                    "preview_xml",
                    "delivery_count",
                    "skipped_message",
                ]
            )
        message = str(caught.exception)
        self.assertIn("business ID", message)
        self.assertIn("contact person", message)
        self.assertIn("no reportable lines", message)
        self.assertIn("payment date", message)
        self.assertIn("already in an Incomes Register", message)

    def test_duplicate_period_warns_and_still_queues(self):
        """Two payslips for one employee and period are a warning, not a block."""
        first = self._done_payslip("First")
        second = self._done_payslip("Second")
        wizard, submissions, _trap = self._queue(first | second)
        self.assertIn(self.employee.name, wizard.warning_message)
        self.assertIn("2", wizard.warning_message)
        self.assertIn("WageReportsRequestToIR", wizard.preview_xml)
        self.assertEqual(len(submissions), 1)
        self.assertEqual(len(submissions.line_ids), 2)

    def test_chunk_size_splits_the_delivery(self):
        """1,201 payslips at 500 reports become three queued deliveries."""
        self.backend.reports_per_delivery = 500
        payslips = self.env["hr.payslip"].create(
            [self._payslip_vals(f"Bulk {index}") for index in range(1201)]
        )
        self.env["hr.payslip.line"].create(
            [self._line_vals(payslip) for payslip in payslips]
        )
        payslips.write({"state": "done"})
        _wizard, submissions, trap = self._queue(payslips)
        self.assertEqual(len(submissions), 3)
        self.assertEqual(
            sorted(len(submission.line_ids) for submission in submissions),
            [201, 500, 500],
        )
        trap.assert_jobs_count(3)
        for call in trap.calls:
            self.assertEqual(call.properties["max_retries"], 1)

    def test_service_address_is_frozen_while_a_delivery_is_open(self):
        """The host can change again once the delivery is no longer in flight."""
        payslip = self._done_payslip("Frozen")
        _wizard, submissions, _trap = self._queue(payslip)
        self.backend.write({"base_url": self.backend.base_url})
        with self.assertRaises(UserError):
            self.backend.write({"base_url": "https://example.test/ir"})
        submissions.write({"state": "error"})
        self.backend.write({"base_url": "https://example.test/ir"})

    def test_status_2_is_received_after_the_claim(self):
        """The row is sending before the call, then received when status is 2."""
        payslip = self._done_payslip("Accepted")
        _wizard, submissions, _trap = self._queue(payslip)
        self._run_send(submissions, result=self._ack(2), check_schema=True)
        self.assertEqual(submissions.state, "received")
        self.assertEqual(submissions.ir_delivery_id, "A" * 32)
        self.assertTrue(submissions.next_poll_at)
        self.assertEqual(submissions.line_ids.state, "pending")
        self.assertTrue(submissions.line_ids.payslip_locked)
        self.assertEqual(payslip.l10n_fi_ir_state, "in_progress")
        self.assertTrue(submissions.request_attachment_id)

    def test_status_4_rejects_the_payslip(self):
        """Status 4 rejects the delivery and releases the payslip."""
        payslip = self._done_payslip("Rejected")
        _wizard, submissions, _trap = self._queue(payslip)
        self._run_send(
            submissions,
            result=self._ack(4, errors=[("ERR", "Record rejected")]),
        )
        self.assertEqual(submissions.state, "rejected")
        self.assertIn("ERR", submissions.error_message)
        self.assertEqual(submissions.line_ids.state, "rejected")
        self.assertFalse(submissions.line_ids.payslip_locked)
        self.assertEqual(payslip.l10n_fi_ir_state, "rejected")

    def test_http_401_is_an_error_and_does_not_raise(self):
        """A refused certificate is stored as an error and the job returns."""
        payslip = self._done_payslip("Refused")
        _wizard, submissions, _trap = self._queue(payslip)
        self._run_send(
            submissions,
            error=IrCallError("error", "The service refused the certificate.", 401),
        )
        self.assertEqual(submissions.state, "error")
        self.assertEqual(submissions.http_status, 401)
        self.assertFalse(submissions.line_ids.payslip_locked)
        self.assertEqual(payslip.l10n_fi_ir_state, "not_sent")

    def test_timeout_is_uncertain_and_is_not_retried(self):
        """A timeout stays uncertain, keeps the lock, and does not raise."""
        payslip = self._done_payslip("Timeout")
        _wizard, submissions, _trap = self._queue(payslip)
        self._run_send(
            submissions,
            error=IrCallError("uncertain", "The connection timed out."),
        )
        self.assertEqual(submissions.state, "uncertain")
        self.assertTrue(submissions.line_ids.payslip_locked)
        self.assertEqual(payslip.l10n_fi_ir_state, "in_progress")
        function = self.env["queue.job.function"].search(
            [
                ("method", "=", "_job_send"),
                ("model_id.model", "=", "l10n_fi.ir.submission"),
            ]
        )
        self.assertFalse(function.retry_pattern)
