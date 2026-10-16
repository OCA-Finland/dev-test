# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.exceptions import UserError


class L10nFiIrNotReceivedWizard(models.TransientModel):
    """Record why a delivery is treated as not received."""

    _name = "l10n_fi.ir.not.received.wizard"
    _description = "Mark Incomes Register Delivery as Not Received"

    submission_id = fields.Many2one(
        "l10n_fi.ir.submission",
        required=True,
        ondelete="cascade",
    )
    note = fields.Text(required=True)

    def action_confirm(self):
        """Set the delivery to not received and keep the note on the chatter.

        The same DeliveryId can then be queued again.

        :return: action that closes the wizard
        :rtype: dict
        :raises UserError: the note is empty or the delivery cannot be closed
        """
        self.ensure_one()
        note = (self.note or "").strip()
        if not note:
            raise UserError(self.env._("Explain why this delivery was not received."))
        submission = self.submission_id
        if submission.state not in ("uncertain", "needs_check"):
            raise UserError(
                self.env._(
                    "Only an uncertain or unchecked delivery can be marked "
                    "as not received."
                )
            )
        submission.write({"state": "not_received", "next_poll_at": False})
        submission.message_post(body=note)
        return {"type": "ir.actions.act_window_close"}

    @api.model
    def default_get(self, fields_list):
        """Keep the active submission when the button did not pass a default.

        :param list fields_list: fields the form asked for
        :return: default values
        :rtype: dict
        """
        values = super().default_get(fields_list)
        if "submission_id" in fields_list and not values.get("submission_id"):
            active = self.env.context.get("active_id")
            if self.env.context.get("active_model") == "l10n_fi.ir.submission":
                values["submission_id"] = active
        return values
