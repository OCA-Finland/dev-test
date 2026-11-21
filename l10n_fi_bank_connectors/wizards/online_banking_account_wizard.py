import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OnlineBankingAccountWizard(models.TransientModel):
    """Wizard for manually registering an online.banking.account (NCA)."""
    _name = 'online.banking.account.wizard'
    _description = 'Add Banking Account'

    connection_id = fields.Many2one(
        comodel_name='online.banking.connection',
        required=True,
        readonly=True,
    )

    iban = fields.Char(
        string="IBAN",
        required=True,
    )

    product = fields.Char(
        string="Product",
    )

    def action_save(self):
        self.ensure_one()
        self._validate()
        account = self.env['online.banking.account'].create({
            'connection_id': self.connection_id.id,
            'iban': self.iban.strip(),
            'name': self.iban.strip(),
            'product': self.product,
        })
        self.connection_id.invalidate_recordset(['bank_account_ids', 'bank_account_count'])
        _logger.info(
            "Manually registered account '%s' for connection '%s'",
            account.iban, self.connection_id.name,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Saved"),
                "message": _("Account '%s' has been registered.") % account.iban,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _validate(self):
        self.ensure_one()
        if not self.iban or not self.iban.strip():
            raise UserError(_("Enter an IBAN before saving."))