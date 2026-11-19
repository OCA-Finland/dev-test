from odoo import fields, models, api

class CreditControlLine(models.Model):
    _inherit = "credit.control.line"

    channel = fields.Selection(
        selection_add=[("invoice", "Invoice")],
        ondelete={"invoice": "cascade"}
    )

    reminder_invoice_id = fields.Many2one(
        "account.move",
        string="Reminder Invoice",
        readonly=True
    )
