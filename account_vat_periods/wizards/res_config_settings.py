from odoo import fields, models, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    closing_id = fields.Many2one(
        "account.period.closing",
        string="Default VAT Closing Template",
        related="company_id.closing_id",
        readonly=False
    )

    mis_report_instance_id = fields.Many2one(
        "mis.report.instance",
        string="Default VAT Report Template",
        related="company_id.mis_report_instance_id",
        readonly=False
    )

    vat_period_duration = fields.Selection(
        selection=[("1", "One month"), ("3", "Three months"), ("12", "A year")],
        string="Default VAT Period Duration for Fiscal Year Auto-creation",
        help="Duration of the Fiscal Year's VAT Periods",
        related="company_id.vat_period_duration",
        required=True,
        readonly=False
    )
    
    partner_id = fields.Many2one(
        "res.partner",
        string="Default Vendor for VAT Payable",
        related="company_id.vat_partner_id",
        readonly=False
    )

    account_id = fields.Many2one(
        "account.account",
        string="Default Account for VAT Payable",
        related="company_id.vat_account_id",
        readonly=False
    )

    payment_reference = fields.Char(
        string="Default Payment Reference for VAT Payable",
        related="company_id.vat_payment_reference",
        readonly=False
    )

    move_name = fields.Char(
        string="Default Description for VAT Payble Line",
        related="company_id.vat_move_name",
        readonly=False
    )

    vat_payment_date = fields.Integer(
        string="Default day of the month for VAT due date (1-31)",
        related="company_id.vat_payment_date",
        readonly=False
    )

    vat_months_between = fields.Integer(
        string="Default amount of months until VAT due date (1-12)",
        related="company_id.vat_months_between",
        readonly=False
    )
