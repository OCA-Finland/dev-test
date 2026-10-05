from odoo import fields, models


class HrEmployee(models.Model):
    """
    Add a field to compute the yearly income for the employee, based on the payslips
    of the current year. The field is computed based on the payslip lines that have
    a category with l10n_fi_ytd_include set to True.
    """

    _inherit = "hr.employee"

    taxcard_ids = fields.One2many("hr.taxcards", "employee_id", string="Verokorttit")
    l10n_fi_yearly_income = fields.Float(
        string="Yearly income",
        required=False,
        default=0.0,
        compute="_compute_yearly_income",
    )

    def _compute_yearly_income(self):
        for record in self:
            ytd_income = 0.0

            last_payslip = self.env["hr.payslip"].search(
                [
                    ("employee_id", "=", record.id),
                    ("state", "in", ["paid", "done"]),
                ],
                limit=1,
                order="date_to desc",
            )
            if last_payslip:
                lines = last_payslip.line_ids.filtered(
                    lambda line: line.category_id.l10n_fi_ytd_include
                )
                if "ytd" in lines:
                    ytd_income += sum(lines.mapped("ytd"))
                else:
                    ytd_income += 0

            record.l10n_fi_yearly_income = ytd_income
