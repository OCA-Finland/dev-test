from odoo import fields, models


class MisReportInstance(models.Model):
    _inherit = "mis.report.instance"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Allowed company",
        default=lambda self: self.env.user.company_id,
        required=False,
    )

    report_id = fields.Many2one(
        "mis.report",
        required=True,
        default=lambda self: self.env['mis.report'].search([('name', '=', 'VAT Return (Arvonlisäveroilmoitus)')], limit=1)[0]
    )