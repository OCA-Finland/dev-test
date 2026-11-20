from odoo import fields, models


class HrPayslipInputType(models.Model):
    """
    This model defines the types of inputs that can be added to a payslip, allowing
    you to control which types of inputs are available for different types of
    payslips.
    """

    _name = "hr.payslip.input.type"
    _description = "Payslip Input Type"

    name = fields.Char(
        required=True,
        translate=True,
        help="Name of the input type, used in payslip input form and in salary rules.",
    )

    code = fields.Char(
        required=True,
        help=(
            "The code that can be used in the salary rules "
            "to refer to this input type"
        ),
    )

    struct_ids = fields.Many2many(
        comodel_name="hr.payroll.structure",
        string="Payroll Structures",
        help="Payroll structures that can use this input type",
    )
