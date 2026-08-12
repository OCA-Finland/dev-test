from odoo import models, fields

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    taxcard_history_ids = fields.One2many('hr.taxcard.history', 'employee_id', string='Verokortti Historia')

class IncomeReport(models.Model):
    _name = 'hr.paysiip_income_report'
    _description = 'Income Reports'

    employee_id = fields.Many2one('hr.employee', string='Työntekijä', required=True, ondelete='cascade')
    date = fields.Date(string='Päivämäärä', required=True)
    tax_percentage = fields.Float(string='Veroprosentti', required=True)
    income_limit = fields.Float(string='Tuloraja')
    additional_percentage = fields.Float(string='Lisäprosentti')
    notes = fields.Text(string='Huomautukset')
    entry_type = fields.Selection([
        ('manual', 'Manuaalinen'),
        ('automatic', 'Automaattinen')
    ], string='Tietojen Syöttötapa', default='manual')