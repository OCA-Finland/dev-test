from odoo import fields, models


class HrDistraintMonthlyFree(models.Model):
    _name = "hr.distraint.monthly.free"
    _description = "Distraint Monthly Free"

    employee_id = fields.Many2one("hr.employee", string="Employee")
    valid_from = fields.Date()
    valid_until = fields.Date()
