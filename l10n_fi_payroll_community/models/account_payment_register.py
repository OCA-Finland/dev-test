from odoo import models


class AccountPaymentRegister(models.TransientModel):
    """
    Inherit the payment register to set the partner bank account of the employee if
    not set and only one is available.
    """

    _inherit = "account.payment.register"

    def _init_payments(self, to_process, edit_mode=False):
        payments = super()._init_payments(to_process, edit_mode=edit_mode)
        for payment in payments:
            if not payment.partner_bank_id and payment.available_partner_bank_ids:
                # If the employee has no bank account, we set the first one
                # available on the partner
                payment.partner_bank_id = payment.available_partner_bank_ids[:1]
        return payments

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)

        if not self.env.context.get("hr_payroll_payment_register"):
            return vals

        if vals.get("partner_bank_id") and not vals.get("partner_id"):
            bank = self.env["res.partner.bank"].browse(vals["partner_bank_id"])
            vals["partner_id"] = bank.partner_id.id

        return vals
