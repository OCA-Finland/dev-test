from odoo import models

class DateRangeGenerator(models.TransientModel):
    _inherit = "date.range.generator"

    def action_apply(self, batch=False):
        gen = super(DateRangeGenerator, self).action_apply()

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
            "December": "Joulukuu"
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
            "Dec": "Joulu"
        }

        date_ranges = self.env["date.range"].search([])

        for date_range in date_ranges:
            try:
                split_name = date_range["name"].split(" ")

                if len(split_name) == 2:
                    first = fi_months_long[split_name[0]]
                    translated = f"{first} {split_name[1]}"

                    date_range.with_context(lang="fi_FI").name = translated
                else:
                    first = fi_months_short[split_name[0]]
                    second = fi_months_short[split_name[2]]
                    translated = f"{first} - {second} {split_name[3]}"

                    date_range.with_context(lang="fi_FI").name = translated
            except:
                continue
