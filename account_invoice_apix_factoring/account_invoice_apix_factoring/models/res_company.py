from odoo import models, fields


class ResCompany(models.Model):
    _inherit = "res.company"

    factoring_edicode = fields.Char(
        string="Factoring eInvoice address",
        help="eInvoice address used as the message receiver when invoices are sent to factoring.",
    )
    factoring_einvoice_operator_id = fields.Many2one(
        comodel_name="res.partner.operator.einvoice",
        string="Factoring eInvoice operator",
        help="eInvoice operator used as the message receiver when invoices are sent to factoring.",
    )