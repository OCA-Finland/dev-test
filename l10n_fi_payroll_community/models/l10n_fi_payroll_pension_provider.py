from odoo import fields, models


class L10nFiPensionProvider(models.Model):
    """
    Model representing pension providers for payroll calculations in Finland
    """

    _name = "l10n.fi.payroll.pension.provider"
    _description = "Pension Provider"
    _order = "code ASC"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
