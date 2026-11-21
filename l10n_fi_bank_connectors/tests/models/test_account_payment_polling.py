from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.addons.queue_job.exception import FailedJobError
from odoo.tests.common import TransactionCase

from ...services.constants.cron import CronPauseReason
from ...services.constants.payments import PaymentStatus, MAX_POLL_AGE_HOURS
from ..test_utils import patch_factory

_FACTORY_PATH = 'odoo.addons.l10n_fi_bank_connectors.models.account_payment_polling.BankingServiceFactory'
_PAUSE_PATH = (
    'odoo.addons.l10n_fi_bank_connectors.models.online_bank_statement_provider_cron_guard.'
    'OnlineBankStatementProviderCronGuard._pause_connection_providers'
)

def _make_mock_response(status=PaymentStatus.PROCESSING):
    mock_response = MagicMock()
    mock_response.status = status
    return mock_response

class TestAccountPaymentPolling(TransactionCase):
    def setUp(self):
        super().setUp()
        self.connection = self.env['online.banking.connection'].create({
            'name': 'Test Connection',
            'api_backend': 'op_corporate_sandbox',
        })
        self.journal = self.env['account.journal'].create({
            'name': 'Test Bank Journal',
            'type': 'bank',
            'code': 'TBNK2',
        })
        self.payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.env.ref('base.main_partner').id,
            'amount': 100.0,
            'journal_id': self.journal.id,
            'banking_connection_id': self.connection.id,
            'banking_payment_id': 'BP123',
        })
        
    @patch(_FACTORY_PATH)
    def test_poll_no_banking_payment_id(self, mock_factory):
        """No banking_payment_id: no service call."""
        self.payment.banking_payment_id = False

        self.payment._job_poll_payment_status()

        mock_factory.from_record_ctx.assert_not_called()
    
    @patch(_FACTORY_PATH)
    def test_poll_age_exceeded(self, mock_factory):
        """Poll age exceeded: posts stall message, no service call."""
        self.payment.banking_poll_started = fields.Datetime.now() - timedelta(hours=MAX_POLL_AGE_HOURS + 1)

        with patch.object(type(self.payment), '_enqueue_poll_job') as mock_enqueue:
            self.payment._job_poll_payment_status()

        mock_factory.from_record_ctx.assert_not_called()
        mock_enqueue.assert_not_called()
        messages = self.payment.message_ids.mapped('body')
        self.assertTrue(any("stopped checking" in m for m in messages))
    
    @patch(_FACTORY_PATH)
    def test_poll_terminal_status_reached(self, mock_factory):
        """Terminal status: applies response, does not re-enqueue."""
        mock_service = MagicMock()
        mock_service.get_payment_status.return_value = _make_mock_response(status=PaymentStatus.PAID)
        patch_factory(mock_factory, mock_service)

        with patch.object(type(self.payment), '_apply_payment_response') as mock_apply, \
             patch.object(type(self.payment), '_enqueue_poll_job') as mock_enqueue:
            self.payment._job_poll_payment_status()

        mock_apply.assert_called_once()
        mock_enqueue.assert_not_called()
        
    @patch(_FACTORY_PATH)
    def test_poll_non_terminal_status(self, mock_factory):
        """Non-terminal status: applies response, re-enqueues next poll."""
        mock_service = MagicMock()
        mock_service.get_payment_status.return_value = _make_mock_response(status=PaymentStatus.PROCESSING)
        patch_factory(mock_factory, mock_service)

        with patch.object(type(self.payment), '_apply_payment_response') as mock_apply, \
             patch.object(type(self.payment), '_enqueue_poll_job') as mock_enqueue:
            self.payment._job_poll_payment_status()

        mock_apply.assert_called_once()
        mock_enqueue.assert_called_once_with()
        
    @patch(_PAUSE_PATH)
    @patch(_FACTORY_PATH)
    def test_poll_auth_error(self, mock_factory, mock_pause):
        """Auth error: pauses connection, raises FailedJobError."""
        mock_factory.from_record_ctx.side_effect = ValueError("token expired")
        mock_factory.is_consent_auth_error.return_value = True

        with self.assertRaises(FailedJobError):
            self.payment._job_poll_payment_status()

        mock_pause.assert_called_once_with(self.connection, reason=CronPauseReason.AUTH_ERROR)
        
    def test_enqueue_payment_status_poll(self):
        """banking_poll_started is set on first call, not overwritten on second."""
        with patch.object(type(self.payment), '_enqueue_poll_job'):
            self.payment.enqueue_payment_status_poll()
            first_started = self.payment.banking_poll_started
            self.payment.enqueue_payment_status_poll()

        self.assertEqual(self.payment.banking_poll_started, first_started)
        
    @patch(_FACTORY_PATH)
    def test_cancel_pending_poll_jobs(self, mock_factory):
        """Only pending/enqueued poll jobs for this payment get cancelled."""
        self.payment._enqueue_poll_job(identity_key='key-1')
        self.payment._enqueue_poll_job(identity_key='key-2')
        jobs = self.env['queue.job'].search([
            ('model_name', '=', 'account.payment'),
            ('method_name', '=', '_job_poll_payment_status'),
            ('state', 'in', ('pending', 'enqueued')),
        ]).filtered(lambda j: self.payment in j.records)
        self.assertEqual(len(jobs), 2)
        jobs[0].state = 'done'

        self.payment._cancel_pending_poll_jobs()

        jobs.invalidate_recordset()
        self.assertEqual(jobs[0].state, 'done')
        self.assertEqual(jobs[1].state, 'cancelled')