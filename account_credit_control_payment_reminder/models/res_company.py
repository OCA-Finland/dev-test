from odoo import fields, models

class ResCompany(models.Model):
    _inherit = "res.company"

    credit_policy_b2c_id = fields.Many2one(
        comodel_name="credit.control.policy",
        string="B2C Credit Control Policy",
        readonly=False,
        help="The B2C Credit Control Policy used "
        "on partners by default. "
        "This setting can be overridden"
        " on partners or invoices.",
    )
