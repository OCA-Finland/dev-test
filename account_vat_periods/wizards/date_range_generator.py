from odoo import models

class DateRangeGenerator(models.TransientModel):
    _inherit = "date.range.generator"

    def action_apply(self, batch=False):
        gen = super(DateRangeGenerator, self).action_apply()

        date_ranges = self._generate_date_ranges(batch=batch)

        for date_range in date_ranges:
            fiscal_year_id = self.env["account.fiscal.year"].search([("date_from", "=", f"{date_ranges[0]['date_start']}")], limit=1)[0]
            date_range_id = self.env["date.range"].search([("name", "=", f"{date_range['name']}")], limit=1)[0]

            self.env["account.vat.period"].create({
                "fiscal_year_id": fiscal_year_id.id,
                "date_range_id": date_range_id.id
            })
            date_range_id.fiscal_year_id = fiscal_year_id
                    
        return gen
