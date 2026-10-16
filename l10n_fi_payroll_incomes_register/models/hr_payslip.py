# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.exceptions import UserError

PROGRESS_SUBMISSION_STATES = {
    "queued",
    "sending",
    "received",
    "uncertain",
    "needs_check",
}


class HrPayslip(models.Model):
    """Show the latest Incomes Register outcome and open the send wizard."""

    _inherit = "hr.payslip"

    l10n_fi_ir_line_ids = fields.One2many(
        "l10n_fi.ir.submission.line",
        "payslip_id",
        string="Incomes Register lines",
    )
    l10n_fi_ir_state = fields.Selection(
        [
            ("not_sent", "Not sent"),
            ("in_progress", "In progress"),
            ("valid", "Valid"),
            ("rejected", "Rejected"),
        ],
        string="Incomes Register",
        compute="_compute_l10n_fi_ir_state",
        store=True,
    )

    @api.depends(
        "l10n_fi_ir_line_ids.state",
        "l10n_fi_ir_line_ids.submission_id.state",
    )
    def _compute_l10n_fi_ir_state(self):
        """Badge the payslip from its latest Incomes Register line.

        A later line replaces an earlier one. A pending line is in progress
        only while that delivery can still be accepted. After a local error
        the payslip can be sent again.

        :return: ``None``
        :rtype: None
        """
        for payslip in self:
            line = payslip.l10n_fi_ir_line_ids.sorted("id")[-1:]
            if not line:
                payslip.l10n_fi_ir_state = "not_sent"
            elif line.state == "valid":
                payslip.l10n_fi_ir_state = "valid"
            elif line.state == "rejected":
                payslip.l10n_fi_ir_state = "rejected"
            elif (
                line.state in ("pending", "unknown")
                and line.submission_id.state in PROGRESS_SUBMISSION_STATES
            ):
                payslip.l10n_fi_ir_state = "in_progress"
            else:
                payslip.l10n_fi_ir_state = "not_sent"

    def action_open_ir_send_wizard(self):
        """Open the send wizard for the done payslips in this selection.

        :return: wizard action
        :rtype: dict
        :raises UserError: none of the selected payslips are done
        """
        done = self.filtered(lambda payslip: payslip.state == "done")
        if not done:
            raise UserError(self.env._("Only payslips in the Done state can be sent."))
        skipped = self - done
        skipped_message = False
        if skipped:
            skipped_message = self.env._(
                "Skipped because they are not done:\n%(payslips)s",
                payslips="\n".join(skipped.mapped("display_name")),
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Send to Incomes Register"),
            "res_model": "l10n_fi.ir.send.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_payslip_ids": [(6, 0, done.ids)],
                "default_skipped_message": skipped_message,
            },
        }

    def _l10n_fi_ir_locked_lines(self):
        """Return Incomes Register lines that still lock these payslips.

        :return: locked lines
        :rtype: l10n_fi.ir.submission.line
        """
        return self.env["l10n_fi.ir.submission.line"].search(
            [
                ("payslip_id", "in", self.ids),
                ("payslip_locked", "=", True),
            ]
        )

    def _l10n_fi_ir_check_unlocked(self):
        """Block draft, cancel, and delete while a delivery still holds the payslip.

        :return: ``None``
        :rtype: None
        :raises UserError: one or more payslips are locked
        """
        locked = self._l10n_fi_ir_locked_lines()
        if not locked:
            return
        raise UserError(
            self.env._(
                "These payslips are in an Incomes Register delivery "
                "and cannot be changed:\n%(payslips)s",
                payslips="\n".join(locked.payslip_id.mapped("display_name")),
            )
        )

    def action_payslip_draft(self):
        """Refuse to reopen a payslip that an Incomes Register delivery holds.

        :return: result of the payroll method
        :rtype: bool
        :raises UserError: a selected payslip is locked
        """
        self._l10n_fi_ir_check_unlocked()
        return super().action_payslip_draft()

    def action_payslip_cancel(self):
        """Refuse to cancel a payslip that an Incomes Register delivery holds.

        :return: result of the payroll method
        :rtype: bool
        :raises UserError: a selected payslip is locked
        """
        self._l10n_fi_ir_check_unlocked()
        return super().action_payslip_cancel()

    def unlink(self):
        """Refuse to delete a payslip that an Incomes Register delivery holds.

        :return: result of the payroll method
        :rtype: bool
        :raises UserError: a selected payslip is locked
        """
        self._l10n_fi_ir_check_unlocked()
        return super().unlink()

    def refund_sheet(self):
        """Refund even when a delivery is open, and warn that the report is not updated.

        The register does not receive a correction from this refund. The
        officer has to fix the report in the Incomes Register.

        :return: action opening the refund payslips
        :rtype: dict
        """
        locked = self.filtered("l10n_fi_ir_line_ids").filtered(
            lambda payslip: payslip._l10n_fi_ir_locked_lines()
        )
        result = super().refund_sheet()
        warning = self.env._(
            "This payslip was refunded while an Incomes Register delivery "
            "is still open. Correct the earnings report manually."
        )
        for payslip in locked:
            payslip.message_post(body=warning)
        return result
