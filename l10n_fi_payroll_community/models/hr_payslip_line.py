from odoo import models, fields, api


class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'
    
    """
    This model extends the standard hr.payslip.line model to add functionality specific to the Finnish payroll requirements,
    such as categorizing payslip lines by input type and calculating aggregated amounts for certain salary rules.
    """

    l10n_fi_code = fields.Char(compute='_compute_l10n_fi_code', store=True)

    aggregated_amount = fields.Float(
        string='Aggregated Amount',
        compute='_compute_aggregated_amount',
        store=True,
    )

    aggregated_uom_id = fields.Many2one(
        related='salary_rule_id.aggregated_uom_id',
        string='Aggregated UoM',
        comodel_name='uom.uom',
        help="Select the unit of measure for the aggregated input types",
        readonly=True,
    )

    exception_warning = fields.Boolean(string='Exception')
    exception_warning_state = fields.Selection([
        ('exception', 'Exception')
        ], compute='_compute_exception_warning_state', store=True)

    @api.depends('salary_rule_id', 'slip_id.input_line_ids')
    def _compute_aggregated_amount(self):
        for rec in self:
            if rec.salary_rule_id.aggregate_input_type_ids:
                # Get the input lines that are aggregated
                input_lines = rec.slip_id.input_line_ids.filtered(
                    lambda l: l.input_type_id in rec.salary_rule_id.aggregate_input_type_ids
                )
                # Sum the amounts of the aggregated input lines
                rec.aggregated_amount = sum(input_lines.mapped('amount_qty'))
            else:
                rec.aggregated_amount = 0.0

    @api.depends('salary_rule_id', 'code')
    def _compute_l10n_fi_code(self):
        for rec in self:
            if rec.salary_rule_id.code is False:
                rec.l10n_fi_code = False
                continue

            parts = rec.salary_rule_id.code.split('_')
            if parts[0].isdigit():
                rec.l10n_fi_code = parts[0]
            else:
                rec.l10n_fi_code = rec.salary_rule_id.code

    
    @api.depends('exception_warning')
    def _compute_exception_warning_state(self):
        for rec in self:
            rec.exception_warning_state = (
                'exception' if rec.exception_warning else False
            )

