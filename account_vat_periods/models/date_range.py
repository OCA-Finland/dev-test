from odoo import fields, models


class DateRange(models.Model):
    _inherit = "date.range"

    fiscal_year_id = fields.Many2one("account.fiscal.year", ondelete="cascade")
