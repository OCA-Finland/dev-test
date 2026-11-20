# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from lxml import etree

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError
from odoo.modules.module import get_module_path

from ..tools.ir_client import IrCallError, post_signed
from ..tools.ir_messages import ack_details, status_details
from ..tools.ir_signature import sign_document
from .ir_backend import WSDL_DIR

_logger = logging.getLogger(__name__)

LOCK_SUBMISSION_STATES = {
    "queued",
    "sending",
    "received",
    "uncertain",
    "needs_check",
    "valid",
    "partially_rejected",
}
LOCK_LINE_STATES = {"pending", "valid"}
CHANNEL = "root.l10n_fi_ir"
# Minutes to wait after each poll that is still processing. The first wait
# of 2 minutes is set when the acknowledgement says the record was received.
POLL_DELAYS_MINUTES = (5, 15, 60)
STATUS_NS = "http://www.tulorekisteri.fi/2017/1/StatusRequestToIR"
CHECK_STATES = {"uncertain", "needs_check"}


class L10nFiIrSubmission(models.Model):
    """One SendWageReports delivery, from queueing through the acknowledgement."""

    _name = "l10n_fi.ir.submission"
    _description = "Incomes Register Submission"
    _inherit = ["mail.thread"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(required=True, copy=False, default="/")
    backend_id = fields.Many2one(
        "l10n_fi.ir.backend",
        required=True,
        ondelete="restrict",
        index=True,
    )
    company_id = fields.Many2one(
        related="backend_id.company_id",
        store=True,
        index=True,
    )
    environment = fields.Selection(
        [("test", "Test"), ("production", "Production")],
        required=True,
    )
    delivery_id = fields.Char(required=True, size=40, copy=False, index=True)
    delivery_data_type = fields.Integer(required=True, default=100)
    payment_date = fields.Date(required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    state = fields.Selection(
        [
            ("queued", "Queued"),
            ("sending", "Sending"),
            ("received", "Received"),
            ("valid", "Valid"),
            ("partially_rejected", "Partially rejected"),
            ("rejected", "Rejected"),
            ("uncertain", "Uncertain"),
            ("needs_check", "Needs check"),
            ("error", "Error"),
            ("not_received", "Not received"),
        ],
        default="queued",
        required=True,
        tracking=True,
        index=True,
    )
    sent_at = fields.Datetime()
    ir_delivery_id = fields.Char(string="IR delivery id", copy=False)
    error_message = fields.Text()
    http_status = fields.Integer(string="HTTP status")
    next_poll_at = fields.Datetime(index=True)
    poll_count = fields.Integer(default=0)
    request_attachment_id = fields.Many2one("ir.attachment", copy=False)
    ack_attachment_id = fields.Many2one("ir.attachment", copy=False)
    status_attachment_id = fields.Many2one("ir.attachment", copy=False)
    line_ids = fields.One2many("l10n_fi.ir.submission.line", "submission_id")
    payslip_count = fields.Integer(compute="_compute_payslip_count")

    _sql_constraints = [
        (
            "delivery_company_type_uniq",
            "unique(company_id, delivery_data_type, delivery_id)",
            "This DeliveryId is already used for the company and record type.",
        )
    ]

    @api.depends("line_ids")
    def _compute_payslip_count(self):
        """Count the payslips on this delivery.

        :return: ``None``
        :rtype: None
        """
        for submission in self:
            submission.payslip_count = len(submission.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        """Assign a sequence number when the wizard did not pass one.

        :param list vals_list: create values
        :return: created submissions
        :rtype: l10n_fi.ir.submission
        """
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == "/":
                vals["name"] = sequence.next_by_code("l10n_fi.ir.submission") or "/"
        return super().create(vals_list)

    def write(self, vals):
        """Keep each payslip lock aligned with this delivery's state.

        :param dict vals: values to write
        :return: ``True``
        :rtype: bool
        """
        result = super().write(vals)
        if "state" in vals:
            self.line_ids._sync_payslip_locked()
        return result

    def action_open_payslips(self):
        """Open the payslips included in this delivery.

        :return: payslip window action
        :rtype: dict
        """
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "payroll.hr_payslip_action"
        )
        action["domain"] = [("id", "in", self.line_ids.payslip_id.ids)]
        action["name"] = self.env._("Payslips")
        action["context"] = {}
        return action

    def _job_send(self):
        """Send this queued delivery once, on a cursor this job owns.

        The row is marked sending and that write is committed before the HTTP
        call. A crash after the call leaves the row sending. This method does
        not raise, so the queue does not retry a call that may have arrived.

        :return: ``None``
        :rtype: None
        """
        self.ensure_one()
        submission_id = self.id
        lang = self.env.lang
        with self.env.registry.cursor() as cr:
            submission = api.Environment(cr, SUPERUSER_ID, {"lang": lang})[
                "l10n_fi.ir.submission"
            ].browse(submission_id)
            try:
                submission._send_claimed()
            except Exception:
                _logger.exception(
                    "Incomes Register delivery %s could not be recorded",
                    submission_id,
                )

    def _send_claimed(self):
        """Claim the row, sign the report, and store the acknowledgement.

        :return: ``None``
        :rtype: None
        """
        self.ensure_one()
        if not self._claim_for_send():
            return
        posted = False
        try:
            document = self._build_signed_request()
            payload = etree.tostring(document, xml_declaration=True, encoding="UTF-8")
            self._store_payload(
                "request_attachment_id",
                f"{self.name}-request.xml",
                payload,
            )
            self._commit_owned_cursor()
            posted = True
            result = self._post_wage_report(document)
            self._apply_ack(result)
            self._commit_owned_cursor()
        except IrCallError as exc:
            _logger.info(
                "Incomes Register delivery %s failed (%s, HTTP %s)",
                self.delivery_id,
                exc.kind,
                exc.http_status,
            )
            self._mark_call_failed(exc.kind, str(exc), exc.http_status)
        except UserError as exc:
            _logger.info(
                "Incomes Register delivery %s was not sent",
                self.delivery_id,
            )
            self._mark_call_failed(
                "error" if not posted else "uncertain",
                str(exc),
                None,
            )
        except Exception:
            _logger.info(
                "Incomes Register delivery %s failed (%s)",
                self.delivery_id,
                "uncertain" if posted else "error",
            )
            self._mark_call_failed(
                "uncertain" if posted else "error",
                self.env._("The delivery could not be sent."),
                None,
            )

    def _claim_for_send(self):
        """Mark a queued row as sending and commit that write.

        ``SKIP LOCKED`` lets a second worker leave the row for whoever already
        holds it. The commit uses this job's cursor, not the cursor that
        queued the job.

        :return: ``True`` when this call claimed the row
        :rtype: bool
        """
        self.env.cr.execute(
            """
            SELECT id FROM l10n_fi_ir_submission
            WHERE id = %s AND state = 'queued'
            FOR UPDATE SKIP LOCKED
            """,
            [self.id],
        )
        if not self.env.cr.fetchone():
            return False
        self.write({"state": "sending", "sent_at": fields.Datetime.now()})
        self._commit_owned_cursor()
        return True

    def _build_signed_request(self):
        """Render, sign, and schema-check the earnings report.

        The stored DeliveryId is reused so a later resend stays the same
        delivery. FaultyControl is 1: one invalid report does not reject the
        rest of the record.

        :return: signed WageReportsRequestToIR element
        :rtype: lxml.etree._Element
        :raises UserError: the report does not match the schema
        """
        self.ensure_one()
        payslips = self.line_ids.sorted("id").payslip_id
        xml = payslips._generate_ir_report_xml(
            payslips,
            self.payment_date,
            self.date_from,
            self.date_to,
            delivery_id=self.delivery_id,
            production=self.environment == "production",
            faulty_control=1,
        )
        document = etree.fromstring(str(xml).strip().encode())
        with self.backend_id._signing_material() as material:
            sign_document(document, material.certificate, material.private_key)
        schema_path = (
            Path(get_module_path("l10n_fi_payroll_community"))
            / "xsd"
            / "WageReportsToIR.xsd"
        )
        schema = etree.XMLSchema(etree.parse(str(schema_path)))
        if not schema.validate(document):
            raise UserError(
                self.env._(
                    "The earnings report does not match the Incomes Register schema."
                )
            )
        return document

    def _post_wage_report(self, document):
        """POST the signed earnings report.

        :param lxml.etree._Element document: signed request
        :return: verified response
        :rtype: IrCallResult
        :raises IrCallError: the call failed or the answer cannot be trusted
        """
        self.ensure_one()
        with self.backend_id._signing_material() as material:
            return post_signed(
                wsdl_dir=os.path.abspath(WSDL_DIR),
                base_url=self.backend_id.base_url,
                service="wage",
                document=document,
                cert_path=material.cert_path,
                key_path=material.key_path,
                ca_bundle_pem=material.ca_bundle_pem,
                env=self.env,
            )

    def _apply_ack(self, result):
        """Store the acknowledgement and move the delivery to its next state.

        Status 2 means the service accepted the record and will process it.
        Status 4 means the record was rejected. Status 0 means it was not
        received, so the payslips can be sent again.

        :param IrCallResult result: verified SendWageReports answer
        :return: ``None``
        :rtype: None
        """
        self.ensure_one()
        self._store_payload(
            "ack_attachment_id",
            f"{self.name}-ack.xml",
            result.content,
        )
        _logger.info(
            "Incomes Register delivery %s answered with HTTP %s",
            self.delivery_id,
            result.http_status,
        )
        try:
            details = ack_details(result.document)
        except (TypeError, ValueError) as exc:
            raise IrCallError(
                "uncertain",
                self.env._("The Incomes Register answer could not be read."),
                result.http_status,
            ) from exc
        vals = {"http_status": result.http_status or 0, "error_message": False}
        if details["ir_delivery_id"]:
            vals["ir_delivery_id"] = details["ir_delivery_id"]
        if details["status"] == 2:
            vals.update(
                {
                    "state": "received",
                    "next_poll_at": fields.Datetime.now() + timedelta(minutes=2),
                }
            )
            self.write(vals)
            return
        if details["status"] == 4:
            vals.update(
                {
                    "state": "rejected",
                    "error_message": details["errors"]
                    or self.env._("The Incomes Register rejected the delivery."),
                }
            )
            self.write(vals)
            self.line_ids.write({"state": "rejected"})
            return
        vals.update(
            {
                "state": "error",
                "error_message": details["errors"]
                or self.env._("The Incomes Register did not accept the delivery."),
            }
        )
        self.write(vals)

    def _mark_call_failed(self, kind, message, http_status):
        """Drop the uncommitted work and store an error or uncertain outcome.

        The claim commit stays. Only writes made after it are rolled back, then
        the outcome is committed on this same cursor.

        :param str kind: ``error`` or ``uncertain``
        :param str message: text safe to show on the submission
        :param int http_status: HTTP status, when a response arrived
        :return: ``None``
        :rtype: None
        """
        cr = self.env.cr
        submission_id = self.id
        lang = self.env.context.get("lang")
        cr.rollback()
        submission = api.Environment(cr, SUPERUSER_ID, {"lang": lang})[
            "l10n_fi.ir.submission"
        ].browse(submission_id)
        submission.write(
            {
                "state": kind if kind in ("error", "uncertain") else "error",
                "error_message": message,
                "http_status": http_status or 0,
            }
        )
        submission._commit_owned_cursor()

    def _commit_owned_cursor(self):
        """Flush this environment and commit the cursor it uses.

        In a test, the cursor from ``registry.cursor`` is a proxy. Its
        ``commit`` flushes the outer transaction, not the environment opened
        on the proxy, so the flush has to happen on this environment first.

        :return: ``None``
        :rtype: None
        """
        self.env.flush_all()
        self.env.cr.commit()  # pylint: disable=invalid-commit

    def _store_payload(self, field_name, filename, payload):
        """Attach an XML payload to this submission.

        :param str field_name: many2one attachment field to set
        :param str filename: attachment name
        :param bytes payload: XML bytes
        :return: ``None``
        :rtype: None
        """
        self.ensure_one()
        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "raw": payload,
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/xml",
            }
        )
        self[field_name] = attachment.id

    @api.model
    def _cron_poll(self):
        """Sweep stalled sends and enqueue status polls that are due.

        A row left in sending for more than 15 minutes is uncertain: the
        call may have reached the service. Received rows are polled on the
        Incomes Register channel. The identity key keeps one poll queued
        per delivery.

        :return: ``None``
        :rtype: None
        """
        deadline = fields.Datetime.now() - timedelta(minutes=15)
        stale = self.search(
            [
                ("state", "=", "sending"),
                ("sent_at", "<=", deadline),
            ]
        )
        if stale:
            stale.write({"state": "uncertain"})
            _logger.info(
                "Incomes Register marked %s stalled deliveries uncertain",
                len(stale),
            )
        due = self.search(
            [
                ("state", "=", "received"),
                ("next_poll_at", "<=", fields.Datetime.now()),
            ]
        )
        for submission in due:
            submission.with_delay(
                channel=CHANNEL,
                identity_key=f"l10n_fi_ir_poll_{submission.id}",
            )._job_poll()

    def _job_poll(self):
        """Ask for the delivery status, or stop when the poll limit is reached.

        A transport failure is raised so the queue can retry this read.
        The delivery stays received until an answer says otherwise.

        :return: ``None``
        :rtype: None
        :raises IrCallError: the status call failed
        """
        self.ensure_one()
        if self.state != "received":
            return
        if self._poll_expired():
            self.write({"state": "needs_check", "next_poll_at": False})
            _logger.info(
                "Incomes Register delivery %s reached the poll limit",
                self.delivery_id,
            )
            return
        self._fetch_and_apply_status()

    def action_check_status(self):
        """Ask for the status now, from an uncertain or unchecked delivery.

        :return: ``True`` so the form reloads
        :rtype: bool
        :raises UserError: this state cannot be checked, or the call failed
        """
        self.ensure_one()
        if self.state not in CHECK_STATES:
            raise UserError(
                self.env._("Only an uncertain or unchecked delivery can be checked.")
            )
        try:
            self._fetch_and_apply_status()
        except IrCallError as exc:
            raise UserError(str(exc)) from exc
        return True

    def action_mark_not_received(self):
        """Open the wizard that records why this delivery never arrived.

        :return: wizard action
        :rtype: dict
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Mark as not received"),
            "res_model": "l10n_fi.ir.not.received.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_submission_id": self.id},
        }

    def action_resend(self):
        """Queue the same DeliveryId again after it was not received.

        :return: ``True``
        :rtype: bool
        :raises UserError: the delivery is not waiting to be sent again
        """
        self.ensure_one()
        if self.state != "not_received":
            raise UserError(
                self.env._("Only a delivery that was not received can be sent again.")
            )
        self.write(
            {
                "state": "queued",
                "error_message": False,
                "http_status": 0,
                "next_poll_at": False,
            }
        )
        self.with_delay(channel=CHANNEL, max_retries=1)._job_send()
        return True

    def _poll_expired(self):
        """Tell whether this delivery has been waiting longer than the limit.

        :return: ``True`` when automatic polling should stop
        :rtype: bool
        """
        self.ensure_one()
        started = self.sent_at or self.create_date
        if not started:
            return False
        hours = self.backend_id.max_poll_hours or 48
        return fields.Datetime.now() >= started + timedelta(hours=hours)

    def _fetch_and_apply_status(self):
        """Send GetDeliveryDataStatus and store the outcome.

        :return: ``None``
        :rtype: None
        :raises IrCallError: the call failed or the answer cannot be read
        :raises UserError: the payer has no business id to put on the request
        """
        self.ensure_one()
        document = self._build_status_request()
        with self.backend_id._signing_material() as material:
            sign_document(document, material.certificate, material.private_key)
            result = post_signed(
                wsdl_dir=os.path.abspath(WSDL_DIR),
                base_url=self.backend_id.base_url,
                service="status",
                document=document,
                cert_path=material.cert_path,
                key_path=material.key_path,
                ca_bundle_pem=material.ca_bundle_pem,
                env=self.env,
            )
        try:
            details = status_details(result.document)
        except (TypeError, ValueError) as exc:
            raise IrCallError(
                "uncertain",
                self.env._("The Incomes Register answer could not be read."),
                result.http_status,
            ) from exc
        self._store_payload(
            "status_attachment_id",
            f"{self.name}-status.xml",
            result.content,
        )
        _logger.info(
            "Incomes Register delivery %s status %s (HTTP %s)",
            self.delivery_id,
            details["status"],
            result.http_status,
        )
        self._apply_status(details, result.http_status)

    def _build_status_request(self):
        """Build an unsigned status request for this delivery.

        The signature is appended by the caller and must stay the last child.
        The request sends this delivery's DeliveryId and, after the service
        has assigned one, its IRDeliveryId. ``StatusRequestToIR`` has no
        ``Source`` element. The payer is identified the same way as on the
        earnings report: type 1 and the business id.

        :return: StatusRequestToIR element
        :rtype: lxml.etree._Element
        :raises UserError: the company has no business id
        """
        self.ensure_one()
        code = self.company_id.company_registry
        if not code:
            raise UserError(
                self.env._(
                    "Company %(company)s has no business ID.",
                    company=self.company_id.display_name,
                )
            )
        root = etree.Element(
            f"{{{STATUS_NS}}}StatusRequestToIR",
            nsmap={"srtir": STATUS_NS},
        )
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
        etree.SubElement(root, "Timestamp").text = timestamp
        etree.SubElement(root, "DeliveryDataType").text = str(self.delivery_data_type)
        etree.SubElement(root, "DeliveryId").text = self.delivery_id
        if self.ir_delivery_id:
            etree.SubElement(root, "IRDeliveryId").text = self.ir_delivery_id
        etree.SubElement(root, "ProductionEnvironment").text = (
            "true" if self.environment == "production" else "false"
        )
        for tag in ("DeliveryDataOwner", "DeliveryDataCreator", "DeliveryDataSender"):
            party = etree.SubElement(root, tag)
            etree.SubElement(party, "Type").text = "1"
            etree.SubElement(party, "Code").text = code
        return root

    def _apply_status(self, details, http_status):
        """Move the delivery according to DeliveryDataStatus.

        Status 3 is processed: a report listed under invalid items is
        rejected and the others are valid. Status 0 means the service does
        not have the record. Any other status keeps the poll going until
        the time limit.

        :param dict details: parsed status document
        :param int http_status: HTTP status of the call
        :return: ``None``
        :rtype: None
        """
        self.ensure_one()
        vals = {"http_status": http_status or 0}
        if details["ir_delivery_id"]:
            vals["ir_delivery_id"] = details["ir_delivery_id"]
        status = details["status"]
        if status == 0:
            vals.update(
                {
                    "state": "not_received",
                    "next_poll_at": False,
                    "error_message": details["errors"]
                    or self.env._(
                        "The Incomes Register has not received this delivery."
                    ),
                }
            )
            self.write(vals)
            return
        if status in (4, 5):
            vals.update(
                {
                    "state": "rejected",
                    "next_poll_at": False,
                    "error_message": details["errors"]
                    or self.env._("The Incomes Register rejected the delivery."),
                }
            )
            self.write(vals)
            self.line_ids.write({"state": "rejected"})
            return
        if status == 3:
            self._apply_processed_items(details, vals)
            return
        self._schedule_next_poll(vals)

    def _apply_processed_items(self, details, vals):
        """Mark each payslip valid or rejected from a processed status.

        :param dict details: parsed status document
        :param dict vals: values already collected for this submission
        :return: ``None``
        :rtype: None
        """
        invalid = {
            item["item_id"]: item["errors"]
            for item in details["invalid_items"]
            if item["item_id"]
        }
        rejected = self.line_ids.filtered(lambda line: line.report_ref in invalid)
        accepted = self.line_ids - rejected
        if accepted:
            accepted.write({"state": "valid", "error_message": False})
        for line in rejected:
            line.write(
                {
                    "state": "rejected",
                    "error_message": invalid[line.report_ref] or False,
                }
            )
        vals.update(
            {
                "state": "partially_rejected" if rejected else "valid",
                "next_poll_at": False,
                "error_message": details["errors"] or False,
            }
        )
        self.write(vals)

    def _schedule_next_poll(self, vals):
        """Wait longer between polls, or stop at the configured limit.

        :param dict vals: values already collected for this submission
        :return: ``None``
        :rtype: None
        """
        if self._poll_expired():
            vals.update(
                {
                    "state": "needs_check",
                    "next_poll_at": False,
                }
            )
            self.write(vals)
            return
        index = min(self.poll_count, len(POLL_DELAYS_MINUTES) - 1)
        delay = POLL_DELAYS_MINUTES[index]
        vals.update(
            {
                "state": "received",
                "poll_count": self.poll_count + 1,
                "next_poll_at": fields.Datetime.now() + timedelta(minutes=delay),
                "error_message": False,
            }
        )
        self.write(vals)


class L10nFiIrSubmissionLine(models.Model):
    """One payslip inside an Incomes Register delivery."""

    _name = "l10n_fi.ir.submission.line"
    _description = "Incomes Register Submission Line"
    _order = "id"
    _check_company_auto = True

    submission_id = fields.Many2one(
        "l10n_fi.ir.submission",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="submission_id.company_id",
        store=True,
        index=True,
    )
    payslip_id = fields.Many2one(
        "hr.payslip",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    report_ref = fields.Char(required=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("valid", "Valid"),
            ("rejected", "Rejected"),
            ("unknown", "Unknown"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    payslip_locked = fields.Boolean(default=False)
    error_message = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        """Lock a payslip as soon as its line is queued.

        :param list vals_list: create values
        :return: created lines
        :rtype: l10n_fi.ir.submission.line
        """
        lines = super().create(vals_list)
        lines._sync_payslip_locked()
        return lines

    def write(self, vals):
        """Update the payslip lock when the line outcome changes.

        :param dict vals: values to write
        :return: ``True``
        :rtype: bool
        """
        result = super().write(vals)
        if "state" in vals:
            self._sync_payslip_locked()
        return result

    def _sync_payslip_locked(self):
        """Set the lock flag that the unique index is built on.

        PostgreSQL cannot index a line by its parent submission's state, so
        the flag is stored here. A payslip stays locked while the delivery
        can still hold that report and the line itself is still in play.

        :return: ``None``
        :rtype: None
        """
        locked = self.filtered(
            lambda line: line.submission_id.state in LOCK_SUBMISSION_STATES
            and line.state in LOCK_LINE_STATES
        )
        to_lock = locked.filtered(lambda line: not line.payslip_locked)
        to_unlock = (self - locked).filtered("payslip_locked")
        if to_lock:
            to_lock.write({"payslip_locked": True})
        if to_unlock:
            to_unlock.write({"payslip_locked": False})

    def init(self):
        """Create the partial unique index that blocks two locks on one payslip.

        :return: result of the parent init
        :rtype: None
        """
        result = super().init()
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            l10n_fi_ir_submission_line_payslip_locked_uniq
            ON l10n_fi_ir_submission_line (payslip_id)
            WHERE payslip_locked
            """
        )
        return result
