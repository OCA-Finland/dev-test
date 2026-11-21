from odoo import _, fields, models
from odoo.exceptions import ValidationError
from odoo.addons.base_iban.models.res_partner_bank import validate_iban

class OnlineBankingAccount(models.Model):
    _name = "online.banking.account"
    _description = "Online Banking Account"
    _rec_name = "name"
    _order = "name"
    
    connection_id = fields.Many2one(
        "online.banking.connection",
        string="Connection",
        ondelete="cascade",
        required=True)
    
    external_account_id = fields.Char(
        string = "External account ID",
        required = False,
    )
    
    iban = fields.Char(
        string = "IBAN",
        required = True
    )
    
    bic = fields.Char(
        string = "BIC",
    )
    
    name = fields.Char(
        string = "Account name",
        required = True,
    )
    
    balance = fields.Monetary(
        string = "Balance",
        currency_field = "currency_id",
    )
    
    currency_id = fields.Many2one(
        "res.currency",
        string = "Currency",
        required = True,
        default=lambda self: self.env.ref('base.EUR').id, 
    )
    
    active = fields.Boolean(
        string = "Active",
        default = True,
    )
    
    product = fields.Char(
        string="Product",
        help="Product name/type as returned by the bank.",
    )
    
    raw_data = fields.Text(
        string="Raw API Data",
    )
    
    partner_bank_id = fields.Many2one(
        comodel_name='res.partner.bank',
        string="Bank Account",
        help="Linked Odoo bank account record (res.partner.bank). "
            "Set via the 'Link Bank Account' wizard.",
        ondelete='set null',
    )

    _sql_constraints = [
            ('unique_external_account_id', 'UNIQUE(connection_id, external_account_id)', 
                'This account is already imported!'),
            ('unique_iban_per_connection', 'UNIQUE(connection_id, iban)',
                'This IBAN is already registered for this connection.'),
        ]

    def _validate_iban_format(self, iban):
        try:
            validate_iban(iban)
        except ValidationError:
            raise ValidationError(_("'%s' is not a valid IBAN.") % iban)

    def create(self, vals_list):
        for vals in ([vals_list] if isinstance(vals_list, dict) else vals_list):
            if vals.get('iban'):
                self._validate_iban_format(vals['iban'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('iban'):
            self._validate_iban_format(vals['iban'])
        return super().write(vals)

    def action_link_partner_bank(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "link.partner.bank.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_banking_account_id": self.id,
                "default_iban": self.iban,
                "default_bic": self.bic or "",
                "default_account_name": self.name,
            },
        }
    
    def _find_matching_partner_bank(self, iban):
        """Find an existing res.partner.bank for the given IBAN."""
        return self.env['res.partner.bank'].search([
            ('acc_number', '=', iban),
            ('partner_id', '=', self.env.company.partner_id.id),
        ], limit=1)
        
    def _find_matching_res_bank(self, bic):
        """Find an existing res.bank matching the given BIC."""
        if not bic:
            return self.env['res.bank']
        return self.env['res.bank'].search([('bic', '=', bic)], limit=1)
    
    def _find_conflicting_account(self, partner_bank, exclude_id=False):
        """Find another online.banking.account already linked to the given partner_bank."""
        if not partner_bank:
            return self.browse()
        domain = [('partner_bank_id', '=', partner_bank.id)]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        return self.search(domain, limit=1)
