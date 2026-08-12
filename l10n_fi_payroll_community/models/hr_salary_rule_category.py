from odoo import models, fields


class HrSalaryRuleCategory(models.Model):
    _inherit = 'hr.salary.rule.category'
    
    """
    This model extends the standard hr.salary.rule.category model to add functionality specific to the Finnish payroll requirements,
    particularly for Year-to-Date (YTD) calculations.
    """

    l10n_fi_ytd_include = fields.Boolean(
        string='Include in YTD',
        help="If checked, this category will be included in the YTD calculation.",
    )
