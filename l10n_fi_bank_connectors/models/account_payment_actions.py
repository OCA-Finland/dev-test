import logging

from odoo import _, models
from odoo.exceptions import UserError

from ..services.constants.payments import PaymentStatus
from ..services.constants.payment_log import PaymentLogEventType
from ..services.service_factory import BankingServiceFactory

_logger = logging.getLogger(__name__)

class AccountPaymentActions(models.Model):
    _inherit = 'account.payment'

    def action_send_payment(self):
        """Validate, generate IDs, initiate payment, apply response."""
        
        self.ensure_one()
        self._assert_sendable()
        self._assert_record_complete()
        self._lock_for_update()
        self.invalidate_recordset(['banking_payment_status'])
        self._assert_sendable()

        connection = self._resolve_and_store_connection()

        with BankingServiceFactory.from_record_ctx(connection) as service:
            service.generate_unique_identification(self)
            response = self._call_initiate(service)
            poll_status = service.supports_status_polling()

        self._apply_payment_response(response, PaymentLogEventType.INITIATION)
        self._log_payment_sent(response)
        
        if response.status not in PaymentStatus.TERMINAL and poll_status:
            self.enqueue_payment_status_poll()
        
        return self._notify_payment_sent(response)
        
    # helpers
    def _lock_for_update(self):
        """Lock the payment row to prevent concurrent sends."""
        self._cr.execute(
            "SELECT id FROM account_payment WHERE id = %s FOR UPDATE",
            (self.id,)
        )
        
    def _resolve_and_store_connection(self):
        """Resolve the banking connection and store it on the payment if not set."""
        connection = self._get_connection()
        if not self.banking_connection_id:
            self.banking_connection_id = connection
        return connection

    def _call_initiate(self, service):
        """Build the DTO and call the bank's payment initiation endpoint."""
        dto = self._build_dto(service)
        try:
            return service.initiate_payment(dto)
        except UserError:
            _logger.warning(
                "Payment rejected: payment_id=%s banking_payment_id=%s origin=validation_or_api",
                self.id, self.banking_payment_id,
            )
            raise
        except Exception:
            _logger.exception(
                "Unexpected error initiating payment: payment_id=%s banking_payment_id=%s",
                self.id, self.banking_payment_id,
            )
            raise
    
    def _log_payment_sent(self, response):
        _logger.info(
            "Payment sent: payment_id=%s banking_payment_id=%s status=%s",
            self.id,
            self.banking_payment_id,
            response.status,
        )
    
    def _notify_payment_sent(self, response):
        title, message, notif_type, sticky = self._build_payment_notification(response)
        return self._build_display_notification(title, message, notif_type, sticky, self._notify_action_open_self())
        
    def _build_payment_notification(self, response):
        """
        Build the notification for a payment initiation response.
        Generic status → title/type/sticky logic lives here.
        Connector-specific user instructions come from response.notification_context().
        """
        status = response.status
        ctx = response.notification_context()
        title, message, notif_type, sticky = self._payment_notification_for_status(status)

        user_instruction = ctx.get("user_instruction", "")
        if user_instruction:
            message = message + "\n" + user_instruction

        return title, message, notif_type, sticky

    def _payment_notification_for_status(self, status):
        """
        Map internal payment status to (title, base_message, notif_type, sticky).
        No connector-specific logic here — connector instructions come from notification_context().
        """
        pid = self.banking_payment_id

        if status == PaymentStatus.PROCESSING:
            return (_("Payment Submitted"), _("Payment %s is being processed by the bank.", pid), "info", False)

        if status == PaymentStatus.PROCESSED:
            return (_("Payment Processed"), _("Payment %s has been successfully processed.", pid), "success", False)

        if status == PaymentStatus.PAID:
            return (_("Payment Paid"), _("Payment %s has been debited and completed.", pid), "success", False)

        if status == PaymentStatus.CONFIRMED:
            return (_("Payment Confirmed"), _("Payment %s has been confirmed and is pending final execution.", pid), "success", False)

        if status == PaymentStatus.PARTIALLY_CONFIRMED:
            return (_("Payment Partially Confirmed"), _("Payment %s has been partially confirmed and is pending final execution.", pid), "warning", True)

        if status == PaymentStatus.PENDING_CONFIRMATION:
            return (_("Payment Pending Confirmation"), _("Payment %s has been created and is awaiting confirmation.", pid), "info", False)

        if status == PaymentStatus.PENDING_USER_APPROVAL:
            return (_("Approval Required"), _("Payment %s requires your approval.", pid), "warning", True)

        if status == PaymentStatus.ON_HOLD:
            return (_("Payment On Hold"), _("Payment %s has been put on hold by the bank.", pid), "warning", True)

        if status == PaymentStatus.USER_APPROVAL_FAILED:
            return (_("Signing Failed"), _("Payment %s signing failed.", pid), "warning", True)

        if status == PaymentStatus.USER_APPROVAL_TIMEOUT:
            return (_("Signing Timed Out"), _("Payment %s signing window expired.", pid), "warning", True)

        if status == PaymentStatus.USER_APPROVAL_CANCELLED:
            return (_("Signing Cancelled"), _("Payment %s signing was cancelled.", pid), "warning", True)

        if status == PaymentStatus.LIMIT_EXCEEDED:
            return (_("Limit Exceeded"), _("Payment %s could not be processed because a limit has been exceeded.", pid), "warning", True)

        if status == PaymentStatus.UNCONFIRMED:
            return (_("Payment Unconfirmed"), _("Payment %s is unconfirmed.", pid), "warning", True)

        if status == PaymentStatus.REJECTED:
            return (_("Payment Rejected"), _("Payment %s was rejected.", pid), "danger", True)

        if status == PaymentStatus.INSUFFICIENT_FUNDS:
            return (_("Insufficient Funds"), _("Payment %s was rejected due to insufficient funds.", pid), "danger", True)

        # fallback — UNRECOGNIZED or anything unmapped
        return (_("Unexpected Status"), _("Payment %s returned an unexpected status.", pid), "warning", True)