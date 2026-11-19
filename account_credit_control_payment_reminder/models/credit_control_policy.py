from odoo import fields, models

class CreditControlPolicyLevel(models.Model):
    _inherit = "credit.control.policy.level"

    channel = fields.Selection(
        selection_add=[("invoice", "Invoice")],
        ondelete={"invoice": "cascade"}
    )

    currency_id = fields.Many2one(
        "res.currency", 
        string="Currency", 
        default=lambda self: self.env.user.company_id.currency_id.id
    )

    reminder_fee = fields.Monetary(
        string="Reminder Fee",
    )

    reminder_interest = fields.Float(
        string="Late Payment Interest Rate",
        digits=(16,5)
    )

    payment_period = fields.Integer(
        string="Payment Period (days)"
    )

    invoice_account_id = fields.Many2one(
        "account.account",
        string="Account for reminder invoice lines"
    )

    reminder_tax_ids = fields.Many2many(
        "account.tax",
        string="Tax rate to use for reminder"
    )

    reminder_note = fields.Char(
        string="Note line for the reminder",
        default=f"Original invoice: %INVOICE Outstanding balance: %OUTSTANDING_BALANCE The interest is calculated from the due date of the original invoice to the due date of the reminder invoice"
    )


class CreditControlPolicy(models.Model):
    _inherit = "credit.control.policy"

    def _due_move_lines_b2c(self, credit_control_run):
        self.ensure_one()
        move_l_obj = self.env["account.move.line"]
        if credit_control_run.company_id.credit_policy_b2c_id.id != self.id:
            return move_l_obj
        domain_line = self._move_lines_domain(credit_control_run)
        return move_l_obj.search(domain_line)

    def _get_move_lines_to_process(self, credit_control_run):
        self.ensure_one()

        if self.id == credit_control_run.company_id.credit_policy_b2c_id.id:
            init_lines = self._due_move_lines_b2c(credit_control_run)
            lines = init_lines.filtered(lambda line: line.partner_id.vat == False and line.partner_id.company_registry == False)
        else:
            init_lines = self._due_move_lines(credit_control_run)
            lines = init_lines.filtered(lambda line: line.partner_id.vat != False or line.partner_id.company_registry != False)

        to_add, to_remove = self._get_partner_related_lines(credit_control_run)
        lines = (lines | to_add) - to_remove
        to_add, to_remove = self._get_invoice_related_lines(credit_control_run)
        lines = (lines | to_add) - to_remove
        return lines
