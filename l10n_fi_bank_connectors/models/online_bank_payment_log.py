import json

from odoo import fields, models

from ..services.constants.payment_log import PaymentLogEventType


class OnlineBankPaymentLog(models.Model):
    _name = 'online.bank.payment.log'
    _description = 'Banking Payment Log'
    _order = 'create_date desc'
    _rec_name = 'create_date'

    payment_id = fields.Many2one(
        comodel_name='account.payment',
        string='Payment',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # provider key
    provider = fields.Char(
        string='Provider',
        readonly=True,
    )
    
    event_type = fields.Selection(
        selection=PaymentLogEventType.SELECTION,
        required=True,
        readonly=True,
        index=True,
    )
    
    signing_url = fields.Char(
        string='Signing url',
        readonly=True,
        index=True,
    )

    # payment status
    status = fields.Char(
        string='Status',
        readonly=True,
    )

    payload_id = fields.Many2one(
        comodel_name='online.bank.payment.raw.response',
        string='Raw Response',
        readonly=True,
        ondelete='set null',
        index=True,
        help="Response body returned by the provider API.",
    )
    
    def _append_payment_log(
        self,
        payment,
        provider,
        event_type,
        signing_url,
        status,
        raw_bytes=None,
    ):
        values = {
            'payment_id': payment.id,
            'provider': provider,
            'event_type': event_type,
            'signing_url': signing_url,
            'status': status,
        }
        if raw_bytes:
            values['payload_id'] = self.env['online.bank.payment.raw.response'].create(
                {'payload': raw_bytes}
            ).id
        return self.env['online.bank.payment.log'].create(values)
