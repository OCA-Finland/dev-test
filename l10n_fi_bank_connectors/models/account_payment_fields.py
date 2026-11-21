from odoo import _, fields, models

from ..services.constants.payments import PaymentStatus


class AccountPaymentFields(models.Model):
    _inherit = 'account.payment'

    # Shared by all providers; 
    # each stores the ID its API needs to identify the
    # payment (OP: instruction_id, Nordea API: payment_id, Nordea Corporate Access:
    # one generated ID used as MsgId, PmtInfId, EndToEndId and InstrId, see HT00238).
    # Deliberately NOT unique: Nordea Corporate Access only requires IDs to be unique
    # within the last 90 calendar days, so a value may legitimately repeat later.
    # Lookups by this value should be scoped to a banking connection.
    banking_payment_id = fields.Char(
        string="Banking payment ID",
        copy=False,
        readonly=True,
        help="Payment ID used for obtaining payment status.",
    )

    banking_payment_status = fields.Selection(
        selection=PaymentStatus.SELECTION,
        string="Banking Payment Status",
        copy=False,
        readonly=True,
        help="Last known status returned by the backend API.",
    )

    banking_connection_id = fields.Many2one(
        comodel_name='online.banking.connection',
        string="Banking Connection",
        copy=False,
        help="The banking connection used to send this payment.",
    )

    banking_backend_family = fields.Selection(
        related='banking_connection_id.backend_family',
    )

    online_bank_payment_log_ids = fields.One2many(
        comodel_name='online.bank.payment.log',
        inverse_name='payment_id',
        string="Payment Logs",
    )
    
    banking_signing_url = fields.Char(
        string="Signing URL",
        compute='_compute_banking_signing_url',
        help="Most recent signing URL received for this payment."
    )
    
    banking_poll_started = fields.Datetime(
        string="Polling Started",
        copy=False,
        readonly=True,
        help="Used to enforce maximum poll age for non-terminal payment statuses.",
    )
