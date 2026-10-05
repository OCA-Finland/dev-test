from odoo import fields, models


class HrSalaryRule(models.Model):
    """
    Add fields to allow aggregation of input types for this salary rule.
    """

    _inherit = "hr.salary.rule"

    aggregate_input_type_ids = fields.Many2many(
        string="Aggregated Input Types",
        comodel_name="hr.payslip.input.type",
        help="Select the input types that should be aggregated for this salary rule",
    )

    aggregated_uom_id = fields.Many2one(
        string="Aggregated UoM",
        comodel_name="uom.uom",
        help="Select the unit of measure for the aggregated input types",
    )

    def _reset_localdict_values(self, localdict):
        localdict = super()._reset_localdict_values(localdict)

        localdict["result_exception_warning"] = False

        return localdict

    def _get_rule_dict(self, localdict):
        res = super()._get_rule_dict(localdict)

        res["exception_warning"] = bool(
            localdict.get("result_exception_warning", False)
        )

        return res
