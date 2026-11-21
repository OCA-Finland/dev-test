import logging

from datetime import timedelta
 
from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.addons.queue_job.exception import FailedJobError
from odoo.addons.queue_job.job import CANCELLED, ENQUEUED, PENDING
 
from ..services.constants.cron import CronPauseReason
from ..services.constants.payments import (
    PaymentStatus, 
    POLL_INTERVAL_MINUTES, 
    MAX_POLL_AGE_HOURS
    )
from ..services.constants.payment_log import PaymentLogEventType
from ..services.service_factory import BankingServiceFactory
 
_logger = logging.getLogger(__name__)


"""Covers methods for payment status polling (manually triggered from the payment form or as a queue job)"""
class AccountPaymentPolling(models.Model):
    _inherit = 'account.payment'
    
    def enqueue_payment_status_poll(self):
        """Enqueue the first status poll job for this payment."""
        self.ensure_one()
        if not self.banking_poll_started:
            self.banking_poll_started = fields.Datetime.now()
            self.flush_recordset(['banking_poll_started'])
        self._enqueue_poll_job(identity_key=f"account.payment-poll-start-{self.id}")

    def action_check_payment_status(self):
        """Manual status poll triggered from the payment form."""
        self.ensure_one()
        if not self.banking_payment_id:
            raise UserError(_("This payment has not been sent yet."))
 
        status = self._fetch_and_apply_payment_status()
 
        _logger.info(
            "Payment status manually checked: payment_id=%s banking_payment_id=%s status=%s",
            self.id,
            self.banking_payment_id,
            status,
        )
 
        if status in PaymentStatus.TERMINAL:
            self._cancel_pending_poll_jobs()
 
        return self._notify_status_updated_simple(status)
    
    def _fetch_and_apply_payment_status(self) -> str:
        """ Poll the bank API for the current payment status and apply the response."""
        connection = self.banking_connection_id
        if not connection:
            raise UserError(_("Payment %s has no banking connection.") % self.id)
 
        with BankingServiceFactory.from_record_ctx(connection) as service:
            response = service.get_payment_status(self.banking_payment_id)
 
        self._apply_payment_response(response, PaymentLogEventType.STATUS_POLL)
        return response.status
    
    # Queue job
    def _enqueue_poll_job(self, identity_key=None):
        """Enqueue a poll job with the configured delay."""
        connection = self.banking_connection_id
        channel = f"root.banking.{connection.api_backend}" if connection else None
        self.with_delay(
            eta=timedelta(minutes=POLL_INTERVAL_MINUTES),
            channel=channel,
            identity_key=identity_key,
            description=(
                f"Poll payment status: {self.name} "
                f"({self.partner_id.name}, {self.amount} {self.currency_id.name}, {self.journal_id.name})"
            ),
        )._job_poll_payment_status()
    
    def _job_poll_payment_status(self):
        """
        Poll the bank for the current payment status. The job can end in:
        1) terminal status: apply the response and stop; no further job enqueued
        2) non-terminal status: apply the response and enqueue the next poll
        """
        self.ensure_one()
 
        if not self.banking_payment_id:
            _logger.warning("Poll job called on payment %s with no banking_payment_id — skipping", self.id,)
            return
 
        if self._poll_age_exceeded():
            _logger.warning(
                "Payment %s (banking_payment_id=%s) exceeded max poll age of %sh — stopping",
                self.id,
                self.banking_payment_id,
                MAX_POLL_AGE_HOURS,
            )
            self.message_post(body=_("We stopped checking this payment's status automatically."))
            return
 
        connection = self.banking_connection_id
        if not connection:
            _logger.warning("Payment %s has no banking connection — cannot poll status", self.id,)
            return
 
        try:
            with BankingServiceFactory.from_record_ctx(connection) as service:
                response = service.get_payment_status(self.banking_payment_id)
        except Exception as exc:
            if BankingServiceFactory.is_consent_auth_error(connection, exc):
                self.env['online.bank.statement.provider']._pause_connection_providers(
                    connection, reason=CronPauseReason.AUTH_ERROR
                )
                raise FailedJobError( _("Authorization expired for connection '%s'; polling stopped.") % connection.name) from exc
            raise

        self._apply_payment_response(response, PaymentLogEventType.STATUS_POLL)
 
        _logger.info( "Payment (with payment_id=%s) status polled: status=%s", self.id, response.status,)
 
        if response.status in PaymentStatus.TERMINAL:
            _logger.info(
                "Payment %s reached terminal status %s — polling stopped",
                self.id,
                response.status,
            )
            return
 
        self._enqueue_poll_job()

    def _poll_age_exceeded(self):
        """Return True if the payment has been polling longer than MAX_POLL_AGE_HOURS."""
        if not self.banking_poll_started:
            return False
        age_limit = self.banking_poll_started + timedelta(hours=MAX_POLL_AGE_HOURS)
        return fields.Datetime.now() > age_limit
    
    def _cancel_pending_poll_jobs(self):
        """Cancel any pending or enqueued status poll jobs for this payment."""
        jobs = self.env['queue.job'].search([
            ('model_name', '=', 'account.payment'),
            ('method_name', '=', '_job_poll_payment_status'),
            ('state', 'in', (PENDING, ENQUEUED)),
        ]).filtered(lambda j: self in j.records)
        if jobs:
            jobs.write({'state': CANCELLED})
            _logger.info(
                "Cancelled %d poll job(s) for payment %s (terminal status reached)",
                len(jobs),
                self.id,
            )
            
    def _notify_status_updated_simple(self, status: str):
        """Return a simple notification for a manual status poll result."""
        return self._build_display_notification(
            _("Status Updated"),
            _("Payment %(id)s status: %(status)s", id=self.banking_payment_id, status=status),
            "info",
            False,
            self._notify_action_open_self(),
        )
