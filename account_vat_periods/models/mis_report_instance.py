from odoo import fields, models, api

class MisReportInstance(models.Model):
    _inherit = "mis.report.instance"

    @api.model
    def _upgrade_legacy_vat_columns(self):
        """Decouple unchanged default columns from company-owned fiscal ranges."""
        legacy_type = self.env.ref("account_fiscal_month.date_range_fiscal_month")
        for suffix, duration in (("month", 1), ("quarter", 3), ("year", 12)):
            column = self.env.ref("account_vat_periods.mis_report_instance_period_vat_" + suffix)
            if (column.mode == "relative" and column.type == "date_range"
                    and column.date_range_type_id == legacy_type
                    and column.offset == 0 and column.duration == duration):
                column.write({"type": "m", "date_range_type_id": False})

    widget_show_date_range = fields.Boolean(
        default=True,
        string="Show Date Range Filter",
        help="Show the Date Range Filter in the report widget bar"
    )

    date_range_name = fields.Char(
        readonly=True,
        compute="_compute_date_range_name"
    )

    @api.depends("date", "date_from", "date_to", "company_id")
    def _compute_date_range_name(self):
        for record in self:
            start = record.date_from or record.date
            end = record.date_to or start
            date_range = self.env["date.range"]
            if start and end:
                date_range = date_range.search([
                    ("company_id", "=", record.company_id.id),
                    ("date_start", "<=", start), ("date_end", ">=", end),
                ], order="date_start desc, id", limit=1)
            record.date_range_name = date_range.name or False

    @api.onchange("widget_show_pivot_date")
    def _onchange_widget_show_pivot_date(self):
        if self.widget_show_pivot_date == True:
            self.widget_show_date_range = False
        else:
            self.widget_show_date_range = True

    @api.onchange("widget_show_date_range")
    def _onchange_widget_show_date_range(self):
        if self.widget_show_date_range == True:
            self.widget_show_pivot_date = False
        else:
            self.widget_show_pivot_date = True

    @api.depends("date")
    def _compute_pivot_date(self):
        super()._compute_pivot_date()

        for record in self:
            if self.env.context.get("date_range"):
                date_range = self.env["date.range"].search([("id", "=", self.env.context.get("date_range")[0]["id"])], limit=1)

                record.pivot_date = date_range.date_start
