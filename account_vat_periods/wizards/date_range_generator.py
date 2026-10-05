from odoo import models


class DateRangeGenerator(models.TransientModel):
    _inherit = "date.range.generator"

    def action_apply(self, batch=False):
        gen = super().action_apply()

        date_ranges = self._generate_date_ranges(batch=batch)

        fi_months_long = {
            "January": "Tammikuu",
            "February": "Helmikuu",
            "March": "Maaliskuu",
            "April": "Huhtikuu",
            "May": "Toukokuu",
            "June": "Kesäkuu",
            "July": "Heinäkuu",
            "August": "Elokuu",
            "September": "Syyskuu",
            "October": "Lokakuu",
            "November": "Marraskuu",
            "December": "Joulukuu",
        }

        fi_months_short = {
            "Jan": "Tammi",
            "Feb": "Helmi",
            "Mar": "Maalis",
            "Apr": "Huhti",
            "May": "Touko",
            "Jun": "Kesä",
            "Jul": "Heinä",
            "Aug": "Elo",
            "Sep": "Syys",
            "Oct": "Loka",
            "Nov": "Marras",
            "Dec": "Joulu",
        }

        for date_range in date_ranges:
            fiscal_year_id = self.env["account.fiscal.year"].search(
                [("date_from", "=", f"{date_ranges[0]["date_start"]}")], limit=1
            )[0]
            date_range_id = self.env["date.range"].search(
                [("name", "=", f"{date_range["name"]}")], limit=1
            )[0]

            vat_period = self.env["account.vat.period"].create(
                {"fiscal_year_id": fiscal_year_id.id, "date_range_id": date_range_id.id}
            )
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
