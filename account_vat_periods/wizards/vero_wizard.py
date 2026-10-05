import calendar
import copy
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .. import vero_payload as payloads
from ..models.vero_backend import GROUP, INTERNAL, check_access


class VeroWizard(models.TransientModel):
    _name = "vero.api.wizard"
    _description = "Preview, submit and inspect Vero returns"

    vat_period_id = fields.Many2one("account.vat.period")
    backend_id = fields.Many2one("vero.api.backend")
    kind = fields.Selection([("vat", "ALV"), ("ec", "EU-yhteenveto")])
    month = fields.Date(string="Yhteenvetoilmoituksen kuukausi")
    report_id = fields.Many2one("vero.api.report", readonly=True)
    status_only = fields.Boolean(default=False)
    no_activity = fields.Boolean(string="Ei toimintaa")
    replace_external = fields.Boolean(
        string="Korvaa aiemmin muualla annettu ALV-ilmoitus"
    )
    replacement_reason = fields.Selection(
        [
            ("CLC", "Lasku- tai täyttövirhe"),
            ("LGL", "Oikeuskäytännön muutos"),
            ("TXA", "Verotarkastuksen ohjaus"),
            ("LAW", "Laintulkintavirhe"),
        ],
        string="Korjauksen syy",
    )
    snapshot = fields.Json(readonly=True)
    preview_body = fields.Json(readonly=True)
    payload_text = fields.Text(readonly=True, string="Lähetettävät tiedot")
    diff_text = fields.Text(
        readonly=True, string="Muutokset edelliseen vastaanotettuun ilmoitukseen"
    )
    history_ids = fields.One2many(related="report_id.submission_ids", readonly=True)
    environment = fields.Selection(related="report_id.environment")
    remote_status = fields.Char(related="report_id.remote_status")
    query_text = fields.Text(compute="_compute_query", string="Viimeisin tilakysely")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("report_id"):
                report = self.env["vero.api.report"].browse(vals["report_id"])
                check_access(report)
                vals.update(
                    kind=report.kind,
                    vat_period_id=report.vat_period_id.id,
                    backend_id=report.backend_id.id,
                    month=report.date_start,
                )
        return super().create(vals_list)

    def _compute_query(self):
        for rec in self:
            rec.query_text = json.dumps(
                rec.report_id.last_query or {}, ensure_ascii=False, indent=2
            )

    def _action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": _("Vero API"),
        }

    def _get_report(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP):
            raise AccessError(_("Show Full Accounting Features is required."))
        if self.report_id:
            check_access(self.report_id)
            return self.report_id
        period = self.vat_period_id
        company = period._vero_company()
        backend = self.backend_id
        if not backend or backend.company_id != company:
            raise UserError(_("Select a Vero connection for the period company."))
        check_access(backend)
        start, end = period.date_range_id.date_start, period.date_range_id.date_end
        if self.kind == "ec":
            if not self.month or not start <= self.month <= end:
                raise UserError(_("Select a month within this VAT period."))
            start = self.month.replace(day=1)
            end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        report_model = self.env["vero.api.report"]
        # Serialize report creation for two simultaneous previews on the period.
        self.env.cr.execute(
            (
                "UPDATE account_vat_period SET write_date=timezone('UTC', now()) WHERE "
                "id=%s"
            ),
            [period.id],
        )
        report = report_model.search(
            [
                ("backend_id", "=", backend.id),
                ("kind", "=", self.kind),
                ("date_end", "=", end),
            ],
            limit=1,
        )
        if not report:
            report = report_model.with_context(_vero_internal=INTERNAL).create(
                {
                    "company_id": company.id,
                    "backend_id": backend.id,
                    "vat_period_id": period.id,
                    "kind": self.kind,
                    "date_start": start,
                    "date_end": end,
                }
            )
        self.report_id = report
        return report

    def action_refresh(self):
        report = self._get_report()
        snapshot = report._payload(no_activity=self.no_activity)
        previous = report._accepted()
        diff = payloads.differences(previous.snapshot if previous else {}, snapshot)
        body = self._request_body(report, snapshot, previous)
        self.write(
            {
                "snapshot": snapshot,
                "preview_body": body,
                "payload_text": json.dumps(body, ensure_ascii=False, indent=2),
                "diff_text": json.dumps(diff, ensure_ascii=False, indent=2)
                if diff
                else "Ei muutoksia.",
            }
        )
        return self._action()

    def _request_body(self, report, snapshot, previous):
        body = copy.deepcopy(snapshot)
        if report.kind == "vat" and (previous or self.replace_external):
            body["ReplacementReturn"] = True
            if self.replacement_reason:
                body["ReplacementReason"] = self.replacement_reason
        if report.kind == "ec" and previous:
            body = payloads.ec_correction(snapshot, previous.snapshot)
        return body

    def action_submit(self):
        report = self._get_report()
        if not self.snapshot:
            raise UserError(_("Preview the report first."))
        check_access(report)
        if report.kind == "vat" and not report.vat_period_id.closed:
            raise UserError(_("Close the VAT period before submitting the VAT return."))
        if report.date_start > fields.Date.context_today(self):
            raise UserError(_("Future periods cannot be sent with this MVP."))
        report.backend_id._connection()  # Missing credentials fail before queuing.
        report._lock()
        if report.submission_ids.filtered(
            lambda s: s.state in ("queued", "sending", "uncertain")
        ):
            raise UserError(
                _(
                    "A submission is pending or its result is uncertain. "
                    "Resolve it before another submission."
                )
            )
        current = report._payload(no_activity=self.no_activity)
        if payloads.digest(current) != payloads.digest(self.snapshot):
            raise UserError(
                _("Report data changed. Refresh and check the preview again.")
            )
        previous = report._accepted()
        if previous and payloads.digest(previous.snapshot) == payloads.digest(current):
            raise UserError(_("No changes compared with the last received return."))
        body = self._request_body(report, current, previous)
        if report.kind == "vat" and (previous or self.replace_external):
            if not self.replacement_reason:
                raise UserError(_("Select the reason for correction."))
        if body != self.preview_body:
            raise UserError(
                _(
                    "The filing content or correction options changed. Refresh the "
                    "preview before confirming."
                )
            )
        if report.kind == "ec" and not body["Buyers"]:
            raise UserError(
                _("No EC sales to report or no changed buyers. Nothing was sent.")
            )
        self.env["vero.api.submission"].with_context(_vero_internal=INTERNAL).create(
            {
                "report_id": report.id,
                "requested_by_id": self.env.uid,
                "environment": report.backend_id.environment,
                "snapshot": current,
                "request_body": body,
                "content_hash": payloads.digest(current),
            }
        )
        self.status_only = True
        return self._action()

    def action_fetch_status(self):
        report = self._get_report()
        report.action_fetch_status()
        return self._action()


class VeroResolution(models.TransientModel):
    _name = "vero.api.resolution"
    _description = "Audited manual resolution of an uncertain submission"

    submission_id = fields.Many2one("vero.api.submission", required=True, readonly=True)
    result = fields.Selection(
        [
            ("received", "Vastaanotto varmistettu Verohallinnosta"),
            ("not_received", "Verohallinto varmisti, ettei lähetystä vastaanotettu"),
        ],
        required=True,
    )
    receipt = fields.Char(string="Verohallinnon vastaanottotunniste")
    accepted_timestamp = fields.Char(string="Verohallinnon vastaanottoaika")
    note = fields.Text(string="Selvityksen lähde ja perustelu", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.check_access("read")
        attempt = self.submission_id
        check_access(attempt.report_id)
        attempt.report_id._lock()
        attempt.invalidate_recordset(["state"])
        if attempt.state != "uncertain":
            raise UserError(
                _("This attempt has already been resolved or is still being processed.")
            )
        if not (self.note or "").strip() or self.result not in (
            "received",
            "not_received",
        ):
            raise UserError(
                _("Record the verified outcome and the source of the verification.")
            )
        vals = {
            "resolved_by_id": self.env.uid,
            "resolved_at": fields.Datetime.now(),
            "resolution_note": self.note,
            "state": "accepted" if self.result == "received" else "not_received",
        }
        if self.result == "received":
            if (
                not (self.receipt or "").strip()
                or not (self.accepted_timestamp or "").strip()
            ):
                raise UserError(
                    _(
                        "Record the receipt identifier and reception time obtained "
                        "from Vero."
                    )
                )
            vals.update(
                receipt=self.receipt.strip(),
                accepted_timestamp=self.accepted_timestamp.strip(),
                bill_message=_(
                    "Vastaanotto vahvistettu käsin. Muodosta tai tarkista lasku "
                    "lähetyksen näkymästä."
                ),
            )
        attempt._update(**vals)
        # Preserve the original request, response and network error for the audit trail.
        return {"type": "ir.actions.act_window_close"}
