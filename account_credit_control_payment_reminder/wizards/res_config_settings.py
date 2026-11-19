from odoo import fields, models, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    credit_policy_b2c_id = fields.Many2one(
        comodel_name="credit.control.policy",
        related="company_id.credit_policy_b2c_id",
        string="B2C Credit Control Policy",
        readonly=False,
        help="The B2C Credit Control Policy used "
        "on partners by default. "
        "This setting can be overridden"
        " on partners or invoices.",
    )
