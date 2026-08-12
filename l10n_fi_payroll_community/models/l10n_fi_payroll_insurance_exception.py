from odoo import models, fields


class L10nFiInsuranceException(models.Model):
    _name = 'l10n.fi.payroll.insurance.exception'
    _description = 'Insurance Exception'
    _order = 'code ASC'
    
    """Model representing insurance exceptions for payroll calculations in Finland."""

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    active = fields.Boolean(string='Active', default=True)