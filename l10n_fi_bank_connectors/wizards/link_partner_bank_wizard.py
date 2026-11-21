import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LinkPartnerBankWizard(models.TransientModel):
    """Wizard to link an online banking account to a res.partner.bank record.

        Raw account data coming from APIs are stored in the online banking account table. 
        Only when a user uses the raw data to create a new res.partner.bank record, they can start
        using it to fetch statements or payment transfers. If a res.partner.bank record with the given
        IBAN and BIC already exists, it will be linked to the online banking account record (unless
        already linked to another record in the online banking account table).
    
    """
    _name = 'link.partner.bank.wizard'
    _description = 'Link Banking Account to Bank Account'

    # fields
    banking_account_id = fields.Many2one(
        comodel_name='online.banking.account',
        required=True,
        readonly=True,
    )

    iban = fields.Char(
        string="IBAN",
        readonly=True,
    )
    bic = fields.Char(
        string="BIC",
        readonly=True,
    )
    account_name = fields.Char(
        string="Account Name",
        readonly=True,
    )

    status_message = fields.Char(
        string="Status",
        compute='_compute_status',
    )
    existing_partner_bank_id = fields.Many2one(
        comodel_name='res.partner.bank',
        compute='_compute_status',
    )
    bank_id = fields.Many2one(
        comodel_name='res.bank',
        compute='_compute_status',
    )
    bank_not_found_warning = fields.Boolean(
        compute='_compute_status',
    )

    @api.depends('iban', 'bic')
    def _compute_status(self):
        """Searches for an existing res.partner.bank record for the current
        company and evaluates whether the bank can be resolved from the BIC.
        """
        for rec in self:
            partner_bank = self.env['online.banking.account']._find_matching_partner_bank(rec.iban)
            rec.existing_partner_bank_id = partner_bank

            bank = self.env['online.banking.account']._find_matching_res_bank(rec.bic)
            rec.bank_id = bank
            rec.bank_not_found_warning = bool(rec.bic and not bank)

            if partner_bank:
                other = self.env['online.banking.account']._find_conflicting_account(partner_bank, exclude_id=rec.banking_account_id.id)
                if other:
                    rec.status_message = _(
                        "A res.partner.bank record with this IBAN already exists "
                        "and is linked to '%(other)s'. Cannot create another link.",
                        other=other.name,
                    )
                else:
                    msg = _("An existing bank account record was found and will be linked.")
                    if rec.bank_not_found_warning:
                        msg += _(" Warning: BIC '%(bic)s' was not found in the bank registry — "
                                 "the existing record will be linked as-is.", bic=rec.bic)
                    rec.status_message = msg
            else:
                msg = _("No existing bank account record found. A new one will be created.")
                if rec.bank_not_found_warning:
                    msg += _(" Warning: BIC '%(bic)s' was not found in the bank registry. "
                             "The bank account will be created without a linked bank.", bic=rec.bic)
                rec.status_message = msg

    def action_confirm(self):
        """Confirm the bank account link."""
        self.ensure_one()

        # block if already linked to another online.banking.account
        if self.existing_partner_bank_id:
            other = self.env['online.banking.account'].search([
                ('partner_bank_id', '=', self.existing_partner_bank_id.id),
                ('id', '!=', self.banking_account_id.id),
            ], limit=1)
            if other:
                raise UserError(
                    _("The bank account with IBAN '%(iban)s' is already linked to '%(other)s'. "
                      "Unlink it there before linking it here.",
                      iban=self.iban, other=other.name)
                )
            partner_bank = self.existing_partner_bank_id
        else:
            partner_bank = self.env['res.partner.bank'].create({
                'acc_number': self.iban,
                'partner_id': self.env.company.partner_id.id,
                'bank_id': self.bank_id.id if self.bank_id else False,
            })
            _logger.info(
                "Created res.partner.bank %s for IBAN %s (connection: %s)",
                partner_bank.id, self.iban, self.banking_account_id.connection_id.name,
            )

        self.banking_account_id.partner_bank_id = partner_bank

        _logger.info(
            "Linked online.banking.account %s to res.partner.bank %s", self.banking_account_id.id, partner_bank.id,)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bank Account Linked"),
                "message": _(
                    "'%(acct)s' has been linked to bank account %(iban)s.",
                    acct=self.banking_account_id.name,
                    iban=self.iban,
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
