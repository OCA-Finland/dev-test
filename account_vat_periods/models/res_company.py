from odoo import fields, models, api, _
from odoo.exceptions import ValidationError

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
        default="1",
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

    vat_payment_date = fields.Integer(
        string="Default day of the month for VAT due date (1-31)",
        default=12
    )

    vat_months_between = fields.Integer(
        string="Default amount of months until VAT due date (1-12)",
        default=2
    )

    @api.constrains("vat_payment_date")
    def _check_vat_payment_date_range(self):
        for record in self:
            if record.vat_payment_date < 1 or record.vat_payment_date > 31:
                raise ValidationError(_("The day of the month must be a value between 1 and 31."))

    @api.constrains("vat_months_between")
    def _check_vat_months_between_range(self):
        for record in self:
            if record.vat_months_between < 1 or record.vat_months_between > 12:
                raise ValidationError(_("The amount of months must be a value between 1 and 12."))
