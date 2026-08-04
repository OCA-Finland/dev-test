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

    #tähän myös se default alv kauden pituus autocreatelle