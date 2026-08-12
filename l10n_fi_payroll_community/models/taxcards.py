from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    taxcard_ids = fields.One2many('hr.taxcards', 'employee_id', string='Verokorttit')

class HrTaxCards(models.Model):
    _name = 'hr.taxcards'
    _description = 'Tax Cards'

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