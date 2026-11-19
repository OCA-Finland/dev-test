from odoo import fields, models

class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_type = fields.Selection(
        selection=[("invoice", "Invoice"), ("reminder", "Reminder Invoice")],
        default="invoice",
        readonly=True
    )
