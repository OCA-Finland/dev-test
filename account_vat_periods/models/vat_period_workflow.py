from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression


class VatPeriodWorkflow(models.Model):
    _inherit = "account.vat.period"

    @api.depends(
        "move_id.line_ids.account_id", "date_range_id.company_id.vat_account_id",
        "fiscal_year_id.company_id.vat_account_id",
    )
    def _compute_vat_payment_type(self):
        for period in self:
            company = period.date_range_id.company_id or period.fiscal_year_id.company_id
            if not period.move_id:
                period.vat_payment_type = "none"
            else:
                period.vat_payment_type = (
                    "payable" if company.vat_account_id in period.move_id.line_ids.account_id else "receivable"
                )

    is_fiscal_start_date = fields.Boolean(
        string="Current fiscal year",
        compute="_compute_is_fiscal_start_date",
        search="_search_is_fiscal_start_date",
        store=False,
        help=(
            "Indicates whether this period belongs to its company's fiscal year containing today's "
            "date. The filter is evaluated when the list is opened, so a new fiscal year or a change "
            "of selected companies does not leave a stale saved flag on the period."
        ),
    )

    @api.depends_context("uid", "allowed_company_ids", "tz")
    @api.depends("fiscal_year_id.date_from", "fiscal_year_id.company_id", "date_range_id.company_id")
    def _compute_is_fiscal_start_date(self):
        today = fields.Date.context_today(self)
        starts = {}
        for period in self:
            # Read only calendar metadata here. Accounting readers may view
            # periods without access to the fiscal-year configuration model.
            year = period.fiscal_year_id.sudo()
            company = period.date_range_id.company_id or year.company_id
            if company and company.id not in starts:
                starts[company.id] = company.sudo().compute_fiscalyear_dates(today)["date_from"]
            period.is_fiscal_start_date = bool(
                company and year
                and year.company_id == company
                and year.date_from == starts[company.id]
            )

    @api.model
    def _search_is_fiscal_start_date(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise NotImplementedError("Use a boolean equality filter for the current fiscal year.")
        today = fields.Date.context_today(self)
        domains = []
        # Limit privileged calendar lookups to the user's selected companies.
        # Return plain IDs so ORM domain expansion does not require fiscal-year
        # configuration access from a user who only reads accounting periods.
        for company in self.env.companies:
            start = company.sudo().compute_fiscalyear_dates(today)["date_from"]
            years = self.env["account.fiscal.year"].sudo().search([
                ("company_id", "=", company.id), ("date_from", "=", start),
            ])
            domains.append([
                ("fiscal_year_id", "in", years.ids),
                ("date_range_id.company_id", "in", [False, company.id]),
            ])
        domain = expression.OR(domains)
        return domain if value == (operator == "=") else ["!"] + expression.normalize_domain(domain)

    def action_open_report_preview(self):
        self.ensure_one()
        self.check_access("read")
        company = self._closing_company()
        template = company.with_company(company).mis_report_instance_id
        if not template or not template.report_id:
            raise UserError(_("Configure the company VAT MIS report template."))
        if template.company_id != company:
            raise UserError(_("The VAT report template must belong to the period company."))
        start, end = self.date_range_id.date_start, self.date_range_id.date_end
        context = {
            "lang": self.env.user.lang or "en_US", "tz": self.env.user.tz or "UTC",
            "allowed_company_ids": company.ids, "mis_analytic_domain": [],
        }
        # Create only a temporary report structure with elevated rights. The
        # client reads ledger values using its own accounting/company access.
        instance = self.env["mis.report.instance"].with_context(context).sudo().create({
            "name": _("VAT report: %s", self.date_range_id.display_name),
            "report_id": template.report_id.id, "company_id": company.id,
            "currency_id": company.currency_id.id, "multi_company": False,
            "target_move": "posted", "temporary": True,
            "date_from": start, "date_to": end, "date": start,
            "widget_show_date_range": False, "widget_show_pivot_date": False,
            "period_ids": [(0, 0, {"name": "VAT", "mode": "fix", "manual_date_from": start, "manual_date_to": end})],
        })
        instance.with_user(self.env.user).check_access("read")
        context.update(active_model="mis.report.instance", active_id=instance.id, active_ids=instance.ids)
        return {
            "name": _("VAT Report Preview"), "type": "ir.actions.act_window",
            "res_model": "mis.report.instance", "res_id": instance.id,
            "view_mode": "form", "view_id": self.env.ref("mis_builder.mis_report_instance_result_view_form").id,
            "target": "current", "context": context,
        }


class DateRangeHistory(models.Model):
    _inherit = "date.range"

    def _check_vat_history(self):
        # Parent deletion can cascade in SQL, bypassing period.unlink().
        periods = self.env["account.vat.period"].sudo().search([("date_range_id", "in", self.ids)])
        periods._check_history_can_be_changed()
        return periods

    def write(self, vals):
        if {"date_start", "date_end", "company_id", "fiscal_year_id"}.intersection(vals):
            self.check_access("write")
            periods = self._check_vat_history()
            with self.env.cr.savepoint():
                result = super().write(vals)
                periods._check_period_company()
            return result
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_vat_history(self):
        self._check_vat_history()


class FiscalYearHistory(models.Model):
    _inherit = "account.fiscal.year"

    def _check_vat_history(self):
        periods = self.env["account.vat.period"].sudo().search([
            "|", ("fiscal_year_id", "in", self.ids), ("date_range_id.fiscal_year_id", "in", self.ids),
        ])
        periods._check_history_can_be_changed()
        return periods

    def write(self, vals):
        if {"date_from", "date_to", "company_id"}.intersection(vals):
            self.check_access("write")
            periods = self._check_vat_history()
            with self.env.cr.savepoint():
                result = super().write(vals)
                periods._check_period_company()
            return result
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_vat_history(self):
        self._check_vat_history()
