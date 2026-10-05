from odoo import fields, models


class L10nFiInsuranceException(models.Model):
    """
    Model representing insurance exceptions for payroll calculations in Finland.
    """

    _name = "l10n.fi.payroll.insurance.exception"
    _description = "Insurance Exception"
    _order = "code ASC"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
