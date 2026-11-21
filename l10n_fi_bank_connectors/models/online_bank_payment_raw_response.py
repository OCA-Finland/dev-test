from odoo import fields, models


class OnlineBankPaymentRawResponse(models.Model):
    _name = 'online.bank.payment.raw.response'
    _description = 'Online Bank Payment Raw Response'

    payload = fields.Binary(
        string='Payload',
        attachment=False,
        required=True,
        readonly=True,
        help="Original response body bytes returned by the provider API.",
    )