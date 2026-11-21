from odoo import models


class AccountPaymentNotifications(models.Model):
    _inherit = 'account.payment'

    def _build_display_notification(self, title, message, notif_type="info", sticky=False, next_action=None):
        """Build an ir.actions.client display_notification dict."""
        params = {
            "title": title,
            "message": message,
            "type": notif_type,
            "sticky": sticky,
        }
        if next_action is not None:
            params["next"] = next_action
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": params,
        }

    def _notify_action_open_self(self):
        """Build a next-action dict that opens this payment's form view."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "res_id": self.id,
            "views": [(False, "form")],
            "target": "current",
        }
