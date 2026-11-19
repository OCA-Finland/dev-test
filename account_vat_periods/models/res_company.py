from odoo import fields, models

class ResCompany(models.Model):
    _inherit = "res.company"

    closing_id = fields.Many2one(
        "account.period.closing",
        string="Default VAT Closing Template",
        check_company=True,
    )

    mis_report_instance_id = fields.Many2one(
        "mis.report.instance",
        string="Default VAT Report Template",
        check_company=True,
    )

    vat_period_duration = fields.Selection(
        selection=[("1", "One month"), ("3", "Three months"), ("12", "A year")],
        string="Default VAT Period Duration for Fiscal Year Auto-creation",
    )
    
    vat_partner_id = fields.Many2one(
        "res.partner",
        string="Default Vendor for VAT Payable",
        check_company=True,
    )

    vat_account_id = fields.Many2one(
        "account.account",
        string="Default Account for VAT Payable",
        check_company=True,
    )

    vat_payment_reference = fields.Char(
        string="Default Payment Reference for VAT Payable",
    )

    vat_move_name = fields.Char(
        string="Default description for VAT Payble Line"
    )
