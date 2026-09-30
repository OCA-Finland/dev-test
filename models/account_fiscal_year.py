from odoo import models, api, fields
from dateutil.rrule import MONTHLY

class AccountFiscalYear(models.Model):
    _inherit = "account.fiscal.year"

    vat_period_duration = fields.Selection(
        selection=[("1", "One month"), ("3", "Three months"), ("12", "A year")],
        string="VAT Period Duration",
        help="Duration of the Fiscal Year's VAT Periods",
        default="1",
        required=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        record = super(AccountFiscalYear, self).create(vals_list)

        fiscal_month_type = self.env["date.range.type"].search([("name", "=", "Fiscal month")], limit=1).id
        duration = record.vat_period_duration
        count = int(12/int(duration))

        if record.vat_period_duration == "1":
            name_expr = "date_start.strftime(f'%B %Y')"
        else:
            name_expr = "date_start.strftime(f'%b - {date_end.strftime('%b')} %Y')"

        self.env["date.range.generator"].create({
            "type_id": fiscal_month_type,
            "company_id": self.env.user.company_id.id,
            "duration_count": duration,
            "unit_of_time": str(MONTHLY),
            "date_start": record.date_from,
            "count": count,
            "name_expr": name_expr
        }).action_apply()

        return record

    def _prepare_next_fiscal_year(self):
        record = super(AccountFiscalYear, self)._prepare_next_fiscal_year()
        record["vat_period_duration"] = self.env.company_id.vat_period_duration
        
        return record
