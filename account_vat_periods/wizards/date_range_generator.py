from odoo import models

class DateRangeGenerator(models.TransientModel):
    _inherit = "date.range.generator"

    def action_apply(self, batch=False):
        gen = super(DateRangeGenerator, self).action_apply()

        date_ranges = self._generate_date_ranges(batch=batch)

        _ = self.with_context(lang='fi_FI').env._
        fi_months_long = {
            'January': _('January'),
            'February': _('February'),
            'March': _('March'),
            'April': _('April'),
            'May': _('May'),
            'June': _('June'),
            'July': _('July'),
            'August': _('August'),
            'September': _('September'),
            'October': _('October'),
            'November': _('November'),
            'December': _('December'),
        }

        fi_months_short = {
            'Jan': _('Jan (short)'),
            'Feb': _('Feb (short)'),
            'Mar': _('Mar (short)'),
            'Apr': _('Apr (short)'),
            'May': _('May (short)'),
            'Jun': _('Jun (short)'),
            'Jul': _('Jul (short)'),
            'Aug': _('Aug (short)'),
            'Sep': _('Sep (short)'),
            'Oct': _('Oct (short)'),
            'Nov': _('Nov (short)'),
            'Dec': _('Dec (short)'),
        }

        for date_range in date_ranges:
            fiscal_year_id = self.env["account.fiscal.year"].search([("date_from", "=", f"{date_ranges[0]["date_start"]}")], limit=1)[0]
            date_range_id = self.env["date.range"].search([("name", "=", f"{date_range["name"]}")], limit=1)[0]

            vat_period = self.env["account.vat.period"].create({
                "fiscal_year_id": fiscal_year_id.id,
                "date_range_id": date_range_id.id
            })
            date_range_id.fiscal_year_id = fiscal_year_id

            if len(date_range["name"].split(" ")) == 2:
                split_name = date_range["name"].split(" ")
                first = fi_months_long[split_name[0]]
                translated = f"{first} {split_name[1]}"

                vat_period.with_context(lang="fi_FI").date_range_id.name = translated
            else:
                split_name = date_range["name"].split(" ")
                first = fi_months_short[split_name[0]]
                second = fi_months_short[split_name[2]]
                translated = f"{first} - {second} {split_name[3]}"

                vat_period.with_context(lang="fi_FI").date_range_id.name = translated

        return gen
