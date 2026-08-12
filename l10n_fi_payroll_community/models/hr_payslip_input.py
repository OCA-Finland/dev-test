from odoo import models, fields


class HrPayslipInput(models.Model):
    _inherit = 'hr.payslip.input'
    """This model extends the standard hr.payslip.input model 
    to add a relation to the HrPayslipInputType model, 
    allowing each payslip input to be categorized by a specific type."""

    input_type_id = fields.Many2one(
        comodel_name='hr.payslip.input.type',
        string='Input Type',
        help="The input type associated with this payslip line, if any",
    )

    code = fields.Char(
        related='input_type_id.code',
        readonly=True
    )