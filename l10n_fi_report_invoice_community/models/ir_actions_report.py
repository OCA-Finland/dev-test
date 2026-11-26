from odoo import models, fields

class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    show_bank_transfer_form = fields.Boolean(
        string="Show Bank Transfer Form", 
        default=False,
        help="Check this to display the bank transfer form at the bottom of the document."
    )
    show_bank_transfer_barcode = fields.Boolean(
        string="Show Virtual Barcode", 
        default=False,
        help="Check this to display the barcode inside the bank transfer form."
    )