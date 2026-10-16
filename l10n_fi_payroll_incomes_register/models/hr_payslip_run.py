# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class HrPayslipRun(models.Model):
    """Open the Incomes Register send wizard for a payslip batch."""

    _inherit = "hr.payslip.run"

    def action_open_ir_send_wizard(self):
        """Open the send wizard for the done payslips of this batch.

        Payslips that are not done are listed as skipped. The download action
        on the batch is left unchanged.

        :return: wizard action
        :rtype: dict
        """
        return self.slip_ids.action_open_ir_send_wizard()
