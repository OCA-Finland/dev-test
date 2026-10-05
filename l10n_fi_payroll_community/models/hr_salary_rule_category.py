from odoo import fields, models


class HrSalaryRuleCategory(models.Model):
    """
    This model extends the standard hr.salary.rule.category model to add
    functionality specific to the Finnish payroll requirements, particularly for
    Year-to-Date (YTD) calculations.
    """

    _inherit = "hr.salary.rule.category"

    l10n_fi_ytd_include = fields.Boolean(
        string="Include in YTD",
        help="If checked, this category will be included in the YTD calculation.",
    )
