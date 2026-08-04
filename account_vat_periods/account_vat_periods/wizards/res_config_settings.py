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
        default="1",
        required=True
    )