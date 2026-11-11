from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.tools.misc import format_date


class AccountFiscalYear(models.Model):
    _inherit = "account.fiscal.year"

    vat_period_duration = fields.Selection(
        [("1", "One month"), ("3", "Three months"), ("12", "A year")],
        string="VAT Period Duration",
        help=(
            "Length of the VAT periods generated when this fiscal year is created. The periods belong "
            "to this fiscal year's company and never extend beyond its end. Verify the filing frequency "
            "with the Finnish Tax Administration; the API checks the official period before submission."
        ),
        default="1", required=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for incoming in vals_list:
            vals = dict(incoming)
            company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
            vals.setdefault("vat_period_duration", company.vat_period_duration or "1")
            prepared.append(vals)
        years = super().create(prepared)
        for year in years:
            year._create_vat_periods()
        return years

    def _vat_period_name(self, start, end, lang):
        if (start.year, start.month) == (end.year, end.month):
            return format_date(self.env, start, lang_code=lang, date_format="MMMM yyyy")
        return "%s - %s" % (
            format_date(self.env, start, lang_code=lang, date_format="MMM yyyy"),
            format_date(self.env, end, lang_code=lang, date_format="MMM yyyy"),
        )

    def _create_vat_periods(self):
        self.ensure_one()
        range_model = self.env["date.range"].with_company(self.company_id)
        range_type = self.env.ref("account_vat_periods.date_range_vat_period")
        months = int(self.vat_period_duration)
        start = self.date_from
        values = []
        while start <= self.date_to:
            boundary = start if months == 12 else start.replace(day=1)
            next_start = boundary + relativedelta(months=months)
            end = min(next_start - relativedelta(days=1), self.date_to)
            values.append({
                "name": self._vat_period_name(start, end, "en_US"),
                "type_id": range_type.id, "company_id": self.company_id.id,
                "fiscal_year_id": self.id, "date_start": start, "date_end": end,
            })
            start = end + relativedelta(days=1)
        ranges = range_model.with_context(lang="en_US").create(values)
        if self.env["res.lang"].search_count([("code", "=", "fi_FI")], limit=1):
            for date_range in ranges:
                date_range.with_context(lang="fi_FI").name = self._vat_period_name(
                    date_range.date_start, date_range.date_end, "fi_FI",
                )
        return self.env["account.vat.period"].with_company(self.company_id).create([
            {"fiscal_year_id": self.id, "date_range_id": date_range.id} for date_range in ranges
        ])

    def _prepare_next_fiscal_year(self):
        values = super()._prepare_next_fiscal_year()
        values["vat_period_duration"] = self.company_id.vat_period_duration or self.vat_period_duration or "1"
        return values
