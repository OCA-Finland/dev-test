from odoo import fields, models, api

class MisReportInstance(models.Model):
    _inherit = "mis.report.instance"

    widget_show_date_range = fields.Boolean(
        default=True,
        string="Show Date Range Filter",
        help="Show the Date Range Filter in the report widget bar"
    )

    date_range_name = fields.Char(
        readonly=True,
        compute="_compute_date_range_name"
    )

    def _compute_date_range_name(self):
        for record in self:
            record.date_range_name = self.env["date.range"].search([("date_start", "<=", record.date), ("date_end", ">=", record.date)], limit=1)[0].name

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
