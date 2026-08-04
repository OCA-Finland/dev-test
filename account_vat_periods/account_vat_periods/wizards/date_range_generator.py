from odoo import models

class DateRangeGenerator(models.TransientModel):
    _inherit = "date.range.generator"

    def action_apply(self, batch=False):
        gen = super(DateRangeGenerator, self).action_apply()

        date_ranges = self._generate_date_ranges(batch=batch)

        fi_months = {
            "January": "Tammikuu",
            "February": "Helmikuu",
            "March": "Maaliskuu",
            "April": "Huhtikuu",
            "May": "Toukokuu",
            "June": "Kesäkuu",
            "July": "Heinäkuu",
            "August": "Elokuu",
            "October": "Lokakuu",
            "November": "Marraskuu",
            "December": "Joulukuu",
            "Jan": "Tammi",
            "Feb": "Helmi",
            "Mar": "Maalis",
            "Apr": "Huhti",
            "May": "Touko",
            "Jun": "Kesä",
            "Jul": "Heinä",
            "Aug": "Elo",
            "Oct": "Loka",
            "Nov": "Marras",
            "Dec": "Joulu"
        }

        for date_range in date_ranges:
            vat_period = self.env["account.vat.period"].create({
                #"name": f"{date_range["name"]}",
                "fiscal_year_id": self.env["account.fiscal.year"].search([("date_from", "=", f"{date_ranges[0]["date_start"]}")], limit=1)[0].id,
                "date_range_id": self.env["date.range"].search([("name", "=", f"{date_range["name"]}")], limit=1)[0].id
            })

            for key in fi_months:
                if key in date_range["name"]:
                    vat_period.with_context(lang="fi_FI").date_range_id.name = date_range["name"].replace(str(key), fi_months[key])
                    break

        return gen
