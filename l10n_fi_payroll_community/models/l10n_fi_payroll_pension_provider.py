from odoo import models, fields


class L10nFiPensionProvider(models.Model):
    _name = 'l10n.fi.payroll.pension.provider'
    _description = 'Pension Provider'
    _order = 'code ASC'
    
    """
    Model representing pension providers for payroll calculations in Finland
    """

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    active = fields.Boolean(string='Active', default=True)