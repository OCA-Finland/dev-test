import json
from datetime import timedelta
from decimal import Decimal

import requests

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.mis_builder.models.accounting_none import AccountingNone
from odoo.addons.mis_builder.models.mis_report_instance import MisReportInstance

from .. import vero_payload as payloads
from .vero_backend import INTERNAL, check_access


class VeroReport(models.Model):
    _name = "vero.api.report"
    _description = "Vero tax report"
    _order = "date_end desc, id desc"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name")
    company_id = fields.Many2one("res.company", required=True, index=True)
    backend_id = fields.Many2one(
        "vero.api.backend", required=True, check_company=True, ondelete="restrict"
    )
    vat_period_id = fields.Many2one(
        "account.vat.period", required=True, ondelete="restrict"
    )
    kind = fields.Selection([("vat", "ALV"), ("ec", "EU-yhteenveto")], required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    environment = fields.Selection(related="backend_id.environment")
    submission_ids = fields.One2many("vero.api.submission", "report_id")
    state = fields.Selection(
        [
            ("draft", "Ei lähetetty"),
            ("queued", "Jonossa"),
            ("sending", "Lähetys kesken / tarkistettava"),
            ("accepted", "Vastaanotettu"),
            ("error", "Virhe"),
            ("uncertain", "Tulos epäselvä"),
            ("not_received", "Selvitetty: ei vastaanotettu"),
        ],
        compute="_compute_state",
    )
    last_query = fields.Json(readonly=True)
    last_query_at = fields.Datetime(readonly=True)
    remote_status = fields.Char(readonly=True)
    due_date = fields.Date(readonly=True)

    _sql_constraints = [
        (
            "vero_report_unique",
            "unique(backend_id,kind,date_end)",
            "This report already exists for this connection and period.",
        )
    ]

    @api.depends("kind", "date_end")
    def _compute_name(self):
        for rec in self:
            kind_label = dict(self._fields["kind"].selection).get(rec.kind, "")
            rec.name = f"{kind_label} {rec.date_end or ''}"

    @api.depends("submission_ids.state")
    def _compute_state(self):
        for rec in self:
            rec.state = (
                rec.submission_ids.sorted("id", reverse=True)[:1].state or "draft"
            )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("_vero_internal") is not INTERNAL:
            raise AccessError(_("Create reports from the VAT period action."))
        return super().create(vals_list).with_context(_vero_internal=None)

    def write(self, vals):
        if self.env.context.get("_vero_internal") is not INTERNAL:
            raise AccessError(_("Report identity and remote state cannot be edited."))
        return super().write(vals)

    def unlink(self):
        if self:
            raise AccessError(_("Vero report history cannot be deleted."))
        return super().unlink()

    def _accepted(self):
        return self.submission_ids.filtered(lambda s: s.state == "accepted").sorted(
            "id", reverse=True
        )[:1]

    def _lock(self):
        self.ensure_one()
        # Odoo uses REPEATABLE READ: SELECT FOR UPDATE alone does not refresh
        # a competing transaction's snapshot. An UPDATE forces its retry.
        self.flush_recordset()
        self.env.cr.execute(
            "UPDATE vero_api_report SET write_date=timezone('UTC', now()) WHERE id=%s",
            [self.id],
        )
        self.invalidate_recordset(["submission_ids", "write_date"])

    def _mis_values(self):
        check_access(self)
        template = self.company_id.mis_report_instance_id
        if not template or not template.report_id:
            raise UserError(_("Configure the company VAT MIS report template."))
        # Only the temporary calculation setup needs MIS-manager privileges.
        # Never forward RPC defaults into privileged creation. Ledger queries
        # below still run as the initiating user, for this company only.
        calculation_context = {
            "lang": self.env.user.lang or "en_US",
            "tz": self.env.user.tz or "UTC",
            "allowed_company_ids": [self.company_id.id],
            "mis_analytic_domain": [],
        }
        instance = (
            self.env["mis.report.instance"]
            .with_context(**calculation_context)
            .sudo()
            .create(
                {
                    "name": "Vero calculation",
                    "report_id": template.report_id.id,
                    "company_id": self.company_id.id,
                    "multi_company": False,
                    "currency_id": self.company_id.currency_id.id,
                    "target_move": "posted",
                    "date_from": self.date_start,
                    "date_to": self.date_end,
                    "temporary": True,
                    "period_ids": [
                        (
                            0,
                            0,
                            {
                                "name": "Vero",
                                "mode": "fix",
                                "manual_date_from": self.date_start,
                                "manual_date_to": self.date_end,
                            },
                        )
                    ],
                }
            )
        )
        try:
            # Base MIS aggregates only. Optional UI partner-detail rows are not tax
            # totals.
            matrix = MisReportInstance._compute_matrix(
                instance.with_user(self.env.user)
            )
            values = {}
            for row in matrix.iter_rows():
                if row.account_id or row.parent_row:
                    continue
                cells = list(row.iter_cells())
                if len(cells) != 1 or cells[0] is None:
                    continue
                val = cells[0].val
                values[row.kpi.name] = 0.0 if val is AccountingNone else val
            # The older installed template uses the former medium-rate label.
            if "vero_13_5" not in values and "vero_14" in values:
                values["vero_13_5"] = values["vero_14"]
            return values
        finally:
            instance.sudo().unlink()

    def _ec_buyers(self):
        backend = self.backend_id
        if not backend.goods_tag_ids or not backend.services_tag_ids:
            raise UserError(
                _(
                    "Configure the EC goods and services tax grids on the Vero "
                    "connection."
                )
            )
        groups = [
            (backend.goods_tag_ids, "SalesOfGoods"),
            (backend.services_tag_ids, "SalesOfServices"),
            (backend.triangulation_tag_ids, "TriangulationSales"),
        ]
        buyers = {}
        for tags, field in groups:
            if not tags:
                continue
            lines = self.env["account.move.line"].search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("parent_state", "=", "posted"),
                    ("date", ">=", self.date_start),
                    ("date", "<=", self.date_end),
                    ("tax_tag_ids", "in", tags.ids),
                    ("tax_line_id", "=", False),
                ]
            )
            for line in lines:
                partner = line.partner_id.commercial_partner_id
                try:
                    key = payloads.vat_identifier(partner.vat)
                except ValueError as exc:
                    raise UserError(
                        _(
                            "%(move)s: %(error)s",
                            move=line.move_id.display_name,
                            error=exc,
                        )
                    ) from exc
                if key[0] == "XI" and field == "SalesOfServices":
                    raise UserError(
                        _(
                            "Northern Ireland EC reporting applies to goods, not "
                            "services."
                        )
                    )
                if key not in buyers:
                    buyers[key] = dict(
                        CountryCode=key[0],
                        VATIdentifier=key[1],
                        **dict.fromkeys(payloads.SALES_FIELDS, Decimal(0)),
                    )
                buyers[key][field] -= Decimal(str(line.balance))
        for row in buyers.values():
            for field in payloads.SALES_FIELDS:
                row[field] = payloads.money(row[field])
        return [
            row
            for row in buyers.values()
            if any(row[field] != 0 for field in payloads.SALES_FIELDS)
        ]

    def _payload(self, no_activity=False):
        self.ensure_one()
        check_access(self)
        if self.company_id.currency_id.name != "EUR":
            raise UserError(_("This MVP supports EUR company accounting only."))
        if self.date_start.year < 2026:
            raise UserError(
                _("This MVP report mapping is validated for periods from 2026.")
            )
        backend = self.backend_id
        try:
            contact = payloads.contact(backend.contact_name, backend.contact_phone)
            if self.kind == "vat":
                return payloads.vat_payload(
                    self._mis_values(),
                    self.company_id.vat,
                    self.date_end,
                    contact,
                    no_activity,
                )
            return payloads.ec_payload(
                self._ec_buyers(), self.company_id.vat, self.date_start, contact
            )
        except ValueError as exc:
            raise UserError(str(exc)) from exc

    def action_preview(self):
        self.ensure_one()
        check_access(self)
        wizard = self.env["vero.api.wizard"].create({"report_id": self.id})
        return wizard.action_refresh()

    def action_status(self):
        self.ensure_one()
        check_access(self)
        wizard = self.env["vero.api.wizard"].create(
            {"report_id": self.id, "status_only": True}
        )
        return wizard._action()

    def action_fetch_status(self):
        self.ensure_one()
        check_access(self)
        if self.kind != "vat":
            raise UserError(
                _(
                    "The EC sales API has no separate status query. The stored "
                    "receipt is shown."
                )
            )
        body = {
            "BusinessId": payloads.business_id(self.company_id.vat),
            "FilingPeriod": str(self.date_end),
        }
        try:
            status, response = self.backend_id._call("GetFiledVATReturn/v2", body)
        except requests.RequestException:
            raise UserError(
                _("The status request failed. The submission state was not changed.")
            ) from None
        self.with_context(_vero_internal=INTERNAL).write(
            {
                "last_query": {"http_status": status, "body": response},
                "last_query_at": fields.Datetime.now(),
                "remote_status": response.get("Status")
                if status == 200 and isinstance(response, dict)
                else "Query error",
            }
        )
        # A fetched old return or a matching amount is not proof of this attempt's
        # receipt.
        return True


class VeroSubmission(models.Model):
    _name = "vero.api.submission"
    _description = "Immutable Vero submission attempt"
    _order = "id desc"

    report_id = fields.Many2one(
        "vero.api.report", required=True, ondelete="restrict", index=True
    )
    company_id = fields.Many2one(related="report_id.company_id", store=True, index=True)
    state = fields.Selection(
        [
            ("queued", "Jonossa"),
            ("sending", "Lähetys kesken / tarkistettava"),
            ("accepted", "Vastaanotettu"),
            ("error", "Virhe"),
            ("uncertain", "Tulos epäselvä"),
            ("not_received", "Selvitetty: ei vastaanotettu"),
        ],
        required=True,
        default="queued",
        readonly=True,
    )
    environment = fields.Selection(
        [("sandbox", "Sandbox"), ("test", "Test"), ("production", "Production")],
        required=True,
        readonly=True,
    )
    requested_by_id = fields.Many2one("res.users", required=True, readonly=True)
    snapshot = fields.Json(required=True, readonly=True)
    request_body = fields.Json(required=True, readonly=True)
    content_hash = fields.Char(required=True, readonly=True)
    response_body = fields.Json(readonly=True)
    http_status = fields.Integer(readonly=True)
    receipt = fields.Char(readonly=True)
    accepted_timestamp = fields.Char(readonly=True)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)
    bill_message = fields.Text(readonly=True)
    bill_id = fields.Many2one("account.move", readonly=True)
    credit_note_id = fields.Many2one("account.move", readonly=True)
    superseded_bill_id = fields.Many2one("account.move", readonly=True)
    resolved_by_id = fields.Many2one("res.users", readonly=True)
    resolved_at = fields.Datetime(readonly=True)
    resolution_note = fields.Text(readonly=True)

    def init(self):
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS vero_one_pending_submission
                ON vero_api_submission (report_id)
                WHERE state IN ('queued', 'sending', 'uncertain')
            """
        )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("_vero_internal") is not INTERNAL:
            raise AccessError(_("Submit through the confirmation wizard."))
        return super().create(vals_list).with_context(_vero_internal=None)

    def write(self, vals):
        if self.env.context.get("_vero_internal") is not INTERNAL:
            raise AccessError(_("Submission history is immutable."))
        return super().write(vals)

    def unlink(self):
        if self:
            raise AccessError(_("Submission history cannot be deleted."))
        return super().unlink()

    def _update(self, **vals):
        return self.with_context(_vero_internal=INTERNAL).write(vals)

    def _preflight(self):
        report = self.report_id
        check_access(report)
        if not self.env.user.active:
            raise UserError(_("The submitting user has been disabled."))
        if (
            report.backend_id.environment != self.environment
            or not report.backend_id.active
        ):
            raise UserError(
                _(
                    "The connection environment changed or was disabled after "
                    "confirmation."
                )
            )
        report.backend_id._connection()
        if report.kind == "vat":
            status, data = report.backend_id._call(
                "GetVATPeriods/v1",
                {
                    "BusinessId": self.request_body["BusinessId"],
                    "FilingYear": report.date_end.year,
                },
            )
            if status != 200 or not isinstance(data, dict):
                raise UserError(
                    _("Could not verify the filing period with Vero: %s")
                    % json.dumps(data, ensure_ascii=False)
                )
            periods = [
                p
                for p in data.get("FilingPeriod", [])
                if p.get("Period") == str(report.date_end)
            ]
            if (
                len(periods) != 1
                or periods[0].get("StartDate") != str(report.date_start)
                or periods[0].get("EndDate") != str(report.date_end)
            ):
                raise UserError(
                    _("The selected period does not match a Vero filing period.")
                )
            info = periods[0]
            remote_state = info.get("Status")
            if remote_state not in {
                "Missing",
                "Processed",
                "Being Processed",
                "Estimated",
            }:
                raise UserError(
                    _("This filing period is expired or has an unsupported status.")
                )
            if remote_state != "Missing" and not self.request_body.get(
                "ReplacementReturn"
            ):
                raise UserError(
                    _(
                        "Vero already has a return for this period. Preview it and "
                        "select replacement of an externally filed return."
                    )
                )
            if (
                remote_state == "Missing"
                and self.request_body.get("ReplacementReturn")
                and not report._accepted()
            ):
                raise UserError(_("Vero has no earlier return to replace."))
            report.with_context(_vero_internal=INTERNAL).write(
                {"due_date": info.get("DueDate"), "remote_status": remote_state}
            )

    def _sync_bill(self):
        self.ensure_one()
        report = self.report_id
        check_access(report)
        if self.state != "accepted" or report.kind != "vat":
            return
        if report._accepted() != self:
            raise UserError(_("Only the latest accepted return can update the bill."))
        if self.credit_note_id:
            return  # An explicitly prepared adjustment must not be prepared twice.
        self.env.cr.execute(
            (
                "UPDATE account_vat_period SET write_date=timezone('UTC', now()) WHERE "
                "id=%s"
            ),
            [report.vat_period_id.id],
        )
        period = report.vat_period_id.with_company(report.company_id)
        period.invalidate_recordset(["payment_move_id"])
        company = report.company_id
        amount = payloads.payable(self.snapshot)
        existing = period.payment_move_id
        if existing and existing.company_id != company:
            raise UserError(_("The linked VAT bill belongs to another company."))
        if self.bill_id and self.bill_id == existing:
            return
        earlier = report.submission_ids.filtered(
            lambda s: s.id < self.id and s.bill_id == existing and s.credit_note_id
        ).sorted("id", reverse=True)[:1]
        credit = (
            existing if existing.move_type == "in_refund" else earlier.credit_note_id
        )
        if existing and existing.move_type == "in_refund":
            if (
                existing.state == "cancel"
                or existing.partner_id != company.vat_partner_id
                or existing.currency_id != company.currency_id
            ):
                raise UserError(
                    _(
                        "Review the existing credit note in accounting before "
                        "another adjustment."
                    )
                )
            # A previous correction to zero/refund may leave a credit note as
            # the period link. Never cancel that credit when VAT changes again.
            move = (
                self._create_vat_bill(amount)
                if amount > 0
                else self.env["account.move"]
            )
            self._update(
                bill_id=move.id,
                credit_note_id=credit.id,
                superseded_bill_id=credit.reversed_entry_id.id,
                bill_message=_(
                    "Aiempi hyvitys säilytettiin. Tarkista oikaisun kirjaukset ja "
                    "maksukohdistukset."
                ),
            )
            period.write({"payment_move_id": move.id or credit.id, "sent": True})
            return
        if (
            existing
            and existing.move_type == "in_invoice"
            and existing.currency_id == company.currency_id
            and existing.partner_id == company.vat_partner_id
            and existing.state != "cancel"
            and company.currency_id.compare_amounts(existing.amount_total, amount) == 0
        ):
            self._update(
                bill_id=existing.id,
                credit_note_id=credit.id,
                superseded_bill_id=credit.reversed_entry_id.id,
                bill_message=earlier.bill_message or False,
            )
            return
        if existing and existing.state == "posted":
            self._update(
                bill_message=_(
                    "Kirjattu tai maksettu lasku: valmistele laskun oikaisu. "
                    "Tarkista ja kirjaa hyvitys sekä uusi lasku ja kohdista maksut "
                    "kirjanpidossa. API-ilmoitus on vastaanotettu."
                )
            )
            return
        if existing and existing.state == "draft":
            existing.button_cancel()
        if credit:
            self._update(
                credit_note_id=credit.id, superseded_bill_id=credit.reversed_entry_id.id
            )
        if amount <= 0:
            self._update(
                bill_message=_(
                    "Ei maksettavaa ALV-laskua. Tarkista mahdollinen "
                    "palautussaatava sulkukirjaukselta."
                )
            )
            period.write({"payment_move_id": credit.id or False, "sent": True})
            return
        move = self._create_vat_bill(amount)
        period.write({"payment_move_id": move.id, "sent": True})
        self._update(bill_id=move.id, bill_message=earlier.bill_message or False)

    def _create_vat_bill(self, amount):
        report, company = self.report_id, self.company_id
        if not company.vat_partner_id or not company.vat_account_id:
            raise UserError(_("Configure the company VAT vendor and payable account."))
        if not report.due_date:
            raise UserError(_("The VAT due date is missing from the period query."))
        return (
            self.env["account.move"]
            .with_company(company)
            .create(
                {
                    "company_id": company.id,
                    "move_type": "in_invoice",
                    "partner_id": company.vat_partner_id.id,
                    "invoice_date": fields.Date.context_today(self),
                    "invoice_date_due": report.due_date,
                    "ref": f"Vero {report.date_end} / {self.receipt}",
                    "payment_reference": company.vat_payment_reference,
                    "invoice_line_ids": [
                        (
                            0,
                            0,
                            {
                                "name": f"ALV {report.date_end}",
                                "account_id": company.vat_account_id.id,
                                "quantity": 1,
                                "price_unit": amount,
                                "tax_ids": [(5, 0, 0)],
                            },
                        )
                    ],
                }
            )
        )

    def action_prepare_bill_adjustment(self):
        self.ensure_one()
        report = self.report_id
        check_access(report)
        report._lock()
        if (
            self.state != "accepted"
            or report.kind != "vat"
            or report._accepted() != self
        ):
            raise UserError(
                _("Only the latest received VAT return can prepare a bill adjustment.")
            )
        self.env.cr.execute(
            (
                "UPDATE account_vat_period SET write_date=timezone('UTC', now()) WHERE "
                "id=%s"
            ),
            [report.vat_period_id.id],
        )
        self.invalidate_recordset(["credit_note_id", "bill_id"])
        period = report.vat_period_id
        period.invalidate_recordset(["payment_move_id"])
        if not self.credit_note_id:
            old = period.payment_move_id
            if not old or old.state != "posted" or old.move_type != "in_invoice":
                raise UserError(
                    _(
                        "A posted vendor bill is required. Draft bills can be "
                        "corrected with the normal bill action."
                    )
                )
            if (
                old.company_id != self.company_id
                or old.currency_id != self.company_id.currency_id
                or old.partner_id != self.company_id.vat_partner_id
            ):
                raise UserError(
                    _(
                        "The original bill must match the report company, currency "
                        "and VAT vendor."
                    )
                )
            if old.reversal_move_ids.filtered(lambda move: move.state != "cancel"):
                raise UserError(
                    _(
                        "The original bill already has a credit note. Review the "
                        "existing adjustment in accounting."
                    )
                )
            amount = payloads.payable(self.snapshot)
            if (
                self.company_id.currency_id.compare_amounts(old.amount_total, amount)
                == 0
            ):
                raise UserError(
                    _(
                        "The payable amount has not changed. No bill adjustment is "
                        "needed."
                    )
                )
            today = fields.Date.context_today(self)
            credit = old._reverse_moves(
                default_values_list=[
                    {
                        "date": today,
                        "invoice_date": today,
                        "ref": (f"Vero correction {report.date_end} / {self.receipt}"),
                    }
                ],
                cancel=False,
            )
            new = (
                self._create_vat_bill(amount)
                if amount > 0
                else self.env["account.move"]
            )
            self._update(
                credit_note_id=credit.id,
                superseded_bill_id=old.id,
                bill_id=new.id,
                bill_message=_(
                    "Oikaisuluonnokset luotu. Tarkista ja kirjaa hyvitys sekä "
                    "mahdollinen uusi lasku. Kohdista hyvitys, huomioi aiempi "
                    "maksu ja tarkista jäljelle jäävä velka tai palautus."
                ),
            )
            period.write({"payment_move_id": new.id or credit.id, "sent": True})
        return {
            "type": "ir.actions.act_window",
            "name": _("ALV-laskun oikaisu"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", (self.credit_note_id | self.bill_id).ids)],
            "target": "current",
        }

    def action_retry_bill(self):
        self.ensure_one()
        check_access(self.report_id)
        self._sync_bill()
        return True

    def action_resolve(self):
        self.ensure_one()
        check_access(self.report_id)
        if self.state != "uncertain":
            raise UserError(_("Only an uncertain submission needs manual resolution."))
        wizard = self.env["vero.api.resolution"].create({"submission_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "name": _("Selvitä epäselvä lähetys"),
        }

    def action_open_bill(self):
        self.ensure_one()
        check_access(self.report_id)
        move = self.bill_id or self.report_id.vat_period_id.payment_move_id
        if not move:
            raise UserError(_("No related bill exists."))
        move.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def _cron_process(self):  # pylint: disable=invalid-commit
        """Commit the claim before the external POST. Never automatically replay it.

        Explicit commits are confined to owned cursors. A crash after the POST
        leaves a visible 'sending' attempt, later marked uncertain, not queued.
        """
        registry = self.env.registry
        for _attempt in range(10):
            with registry.cursor() as cr:
                admin = api.Environment(cr, SUPERUSER_ID, {})
                cr.execute(
                    "SELECT id FROM vero_api_submission WHERE state='queued' ORDER "
                    "BY id FOR UPDATE SKIP LOCKED LIMIT 1"
                )
                row = cr.fetchone()
                if not row:
                    break
                record = admin["vero.api.submission"].browse(row[0])
                uid, company = record.requested_by_id.id, record.company_id.id
                record._update(state="sending", started_at=fields.Datetime.now())
                cr.commit()  # pylint: disable=invalid-commit
                user_env = api.Environment(cr, uid, {"allowed_company_ids": [company]})
                submission = user_env["vero.api.submission"].browse(row[0])
                posted = False
                try:
                    submission._preflight()
                    # Validate and persist read-only preflight results before POST.
                    cr.commit()  # pylint: disable=invalid-commit
                    operation = (
                        "FileVATReturn/v2"
                        if submission.report_id.kind == "vat"
                        else "FileECSalesList/v1"
                    )
                    posted = True
                    code, data = submission.report_id.backend_id._call(
                        operation, submission.request_body
                    )
                    accepted = payloads.received_response(code, data)
                    state = (
                        "accepted"
                        if accepted
                        else ("error" if 400 <= code < 500 else "uncertain")
                    )
                    submission._update(
                        state=state,
                        response_body=data,
                        http_status=code,
                        receipt=data.get("UniqueIdentifier") if accepted else False,
                        accepted_timestamp=data.get("AcceptedTimestamp")
                        if accepted
                        else False,
                        finished_at=fields.Datetime.now(),
                        error_message=False
                        if accepted
                        else self.env._(
                            "Vero did not return a valid reception receipt. See "
                            "response."
                        ),
                    )
                    cr.commit()  # pylint: disable=invalid-commit
                    if accepted:
                        try:
                            with cr.savepoint():
                                submission._sync_bill()
                        except Exception as exc:
                            submission._update(
                                bill_message=self.env._(
                                    "Ilmoitus vastaanotettu; laskuvaihe epäonnistui: %s"
                                )
                                % str(exc)
                            )
                        cr.commit()  # pylint: disable=invalid-commit
                except Exception as exc:
                    cr.rollback()
                    # User may have lost access; only the scheduler finalizes its own
                    # claim.
                    safe = api.Environment(cr, SUPERUSER_ID, {})[
                        "vero.api.submission"
                    ].browse(row[0])
                    message = (
                        self.env._("Network error. Verify receipt before retrying.")
                        if isinstance(exc, requests.RequestException)
                        else str(exc)
                    )
                    # A committed receipt must survive even a later bookkeeping failure.
                    if safe.state == "accepted":
                        safe._update(
                            bill_message=self.env._(
                                "Ilmoitus vastaanotettu; tarkista laskuvaihe: %s"
                            )
                            % message
                        )
                    else:
                        safe._update(
                            state="uncertain" if posted else "error",
                            error_message=message,
                            finished_at=fields.Datetime.now(),
                        )
                    cr.commit()  # pylint: disable=invalid-commit
        stale = self.search(
            [
                ("state", "=", "sending"),
                ("started_at", "<", fields.Datetime.now() - timedelta(minutes=15)),
            ]
        )
        # The last owned cursor is closed here. Do not let the global _()
        # helper infer a cursor from local variables in a language-less cron.
        stale._update(
            state="uncertain",
            error_message=self.env._(
                "Processing was interrupted. Verify the receipt; the request will "
                "not be resent automatically."
            ),
        )
