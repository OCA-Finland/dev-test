from odoo import models, fields


class HrPayslipInputType(models.Model):
    _name = 'hr.payslip.input.type'
    _description = 'Payslip Input Type'
    
    """
    This model defines the types of inputs that can be added to a payslip, 
    allowing you to control which types of inputs are available for different types of payslips.
    """


    name = fields.Char(
        string='Name',
        required=True,
        translate=True,
        help="Name of the input type, used in payslip input form and in salary rules."
    )

    code = fields.Char(
        string='Code',
        required=True,
        help="The code that can be used in the salary rules to refer to this input type"
    )

    struct_ids = fields.Many2many(
        comodel_name='hr.payroll.structure',
        string='Payroll Structures',
        help="Payroll structures that can use this input type"
    )
