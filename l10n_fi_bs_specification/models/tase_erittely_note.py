# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class TaseErittelyNote(models.Model):
    _name = "tase.erittely.note"
    _description = "Tase-erittelyn manuaalinen erittely"
    _order = "date_to desc, account_id"

    account_id = fields.Many2one(
        "account.account",
        string="Tili",
        required=True,
        domain=[("tase_erittely_type", "=", "manual")],
    )
    company_id = fields.Many2one(
        "res.company",
        string="Yhtiö",
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="Tilikausi alkaa", required=True)
    date_to = fields.Date(string="Tilikausi päättyy", required=True)
    note = fields.Html(string="Erittely")

    _sql_constraints = [
        (
            "account_period_company_uniq",
            "unique(account_id, company_id, date_from, date_to)",
            "Tälle tilille ja tilikaudelle on jo olemassa erittely.",
        )
    ]
