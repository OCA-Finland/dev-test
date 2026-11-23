from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ...services.constants.connection import ConnectionStatus
from ...services.dtos import AccountDTO
from ...services.error_handling.error_types import AccountRefreshNotSupported
from ...services.soap.nordea_corporate_access.nordea_ca_dtos import ApplicationResponseDTO
from ..test_utils import patch_factory, make_connection

_SCHEDULE_PATH = 'odoo.addons.l10n_fi_bank_connectors.models.online_banking_connection_actions.schedule_for_family'
_FACTORY_PATH = 'odoo.addons.l10n_fi_bank_connectors.models.online_banking_connection_actions.BankingServiceFactory'


def _make_account_dto(external_id='acc_1', iban='FI2112345600000785', name='Test Account', balance=1000.0):
    return AccountDTO(
        external_id=external_id,
        iban=iban,
        currency='EUR',
        name=name,
        balance=balance,
        raw={'balance': balance},
    )

@patch(_FACTORY_PATH)
class TestOnlineBankingConnectionActions(TransactionCase):

    def setUp(self):
        super().setUp()
        self.connection = make_connection(self.env)
    
    def test_action_test_connection_success(self, mock_factory):
        mock_service = MagicMock(spec=['get_accounts', 'provider_name'])
        mock_service.get_accounts.return_value = [_make_account_dto()]
        mock_service.provider_name = "Mock Provider"
        patch_factory(mock_factory, mock_service)

        # test
        action = self.connection.action_test_connection()

        # assertions
        self.assertEqual(action['params']['type'], 'success')
        self.assertIn('1 account(s) found', action['params']['message'])
        
    def test_action_test_connection_with_probe_auth(self, mock_factory):
        mock_service = MagicMock(spec=['probe_auth', 'provider_name'])
        mock_service.provider_name = "Mock Provider"
        mock_service.probe_auth.return_value = ApplicationResponseDTO(
            response_code="OK",
            response_text="Success",
        )
        patch_factory(mock_factory, mock_service)

        # test
        action = self.connection.action_test_connection()

        # assertions
        mock_service.probe_auth.assert_called_once()
        self.assertEqual(action['params']['type'], 'success')
        self.assertIn('OK', action['params']['message'])
        
    def test_action_test_connection_failure(self, mock_factory):
        mock_factory.from_record_ctx.side_effect = ValueError("Invalid credentials")

        with self.assertRaisesRegex(UserError, "Connection test failed: Invalid credentials"):
            self.connection.action_test_connection()
            
    def test_action_fetch_accounts_creates_new(self, mock_factory):
        mock_service = MagicMock()
        mock_service.refresh_accounts.return_value = [
            _make_account_dto('acc_1', 'FI2112345600000785', 'Account 1'),
            _make_account_dto('acc_2', 'FI1410093000123458', 'Account 2'),
        ]
        patch_factory(mock_factory, mock_service)

        # test
        action = self.connection.action_fetch_accounts()

        # assertions
        accounts = self.env['online.banking.account'].search([
            ('connection_id', '=', self.connection.id)
        ])
        self.assertEqual(len(accounts), 2)
        self.assertEqual(action['params']['type'], 'success')
        self.assertIn('2 new account(s)', action['params']['message'])
    
    def test_action_fetch_accounts_updates_existing(self, mock_factory):
        self.env['online.banking.account'].create({
            'connection_id': self.connection.id,
            'external_account_id': 'acc_1',
            'iban': 'FI2112345600000785',
            'name': 'Old Name',
            'balance': 500.0,
            'currency_id': self.env.ref('base.EUR').id,
        })
        mock_service = MagicMock()
        mock_service.refresh_accounts.return_value = [
            _make_account_dto('acc_1', 'FI2112345600000785', 'New Name', 1500.0),
        ]
        patch_factory(mock_factory, mock_service)

        # test
        action = self.connection.action_fetch_accounts()

        # assertions
        accounts = self.env['online.banking.account'].search([
            ('connection_id', '=', self.connection.id)
        ])
        self.assertEqual(accounts[0].name, 'New Name')
        self.assertIn('1 updated', action['params']['message'])
    
    def test_action_fetch_accounts_service_failure(self, mock_factory):
        mock_factory.from_record_ctx.side_effect = UserError("API is offline")

        with self.assertRaisesRegex(UserError, "Failed to fetch accounts: API is offline"):
            self.connection.action_fetch_accounts()

    def _make_due(self, connection):
        connection.account_info_next_run = fields.Datetime.now() - timedelta(hours=1)
        return connection

    def _cron(self):
        self.env['online.banking.connection']._cron_refresh_account_info()

    def test_cron_refresh_syncs_due_connection(self, mock_factory):
        connection = self._make_due(make_connection(self.env, status=ConnectionStatus.ACTIVE))
        mock_service = MagicMock(spec=['refresh_accounts', 'provider_name'])
        mock_service.refresh_accounts.return_value = [_make_account_dto()]
        patch_factory(mock_factory, mock_service)

        self._cron()

        self.assertEqual(len(connection.bank_account_ids), 1)
        self.assertTrue(connection.account_info_last_synced_at)
        self.assertGreater(connection.account_info_next_run, fields.Datetime.now())

    def test_cron_refresh_skips_connection_not_due(self, mock_factory):
        connection = make_connection(self.env, status=ConnectionStatus.ACTIVE)
        next_run = connection.account_info_next_run

        self._cron()

        mock_factory.from_record_ctx.assert_not_called()
        self.assertEqual(connection.account_info_next_run, next_run)

    def test_cron_refresh_ignores_non_active_connection(self, mock_factory):
        connection = self._make_due(
            make_connection(self.env, name='Pending', status=ConnectionStatus.PENDING)
        )
        next_run = connection.account_info_next_run

        self._cron()

        mock_factory.from_record_ctx.assert_not_called()
        self.assertEqual(connection.account_info_next_run, next_run)

    def test_cron_refresh_not_supported_advances_next_run(self, mock_factory):
        connection = self._make_due(make_connection(self.env, status=ConnectionStatus.ACTIVE))
        mock_service = MagicMock(spec=['refresh_accounts', 'provider_name'])
        mock_service.refresh_accounts.side_effect = AccountRefreshNotSupported("no feed")
        patch_factory(mock_factory, mock_service)

        self._cron()

        self.assertFalse(connection.account_info_last_synced_at)
        self.assertGreater(connection.account_info_next_run, fields.Datetime.now())

    def test_cron_refresh_failure_advances_and_continues(self, mock_factory):
        failing = self._make_due(
            make_connection(self.env, name='Failing', status=ConnectionStatus.ACTIVE)
        )
        working = self._make_due(
            make_connection(self.env, name='Working', status=ConnectionStatus.ACTIVE)
        )
        mock_service = MagicMock(spec=['refresh_accounts', 'provider_name'])
        mock_service.refresh_accounts.return_value = [_make_account_dto()]
        patch_factory(mock_factory, mock_service)
        ok_ctx = mock_factory.from_record_ctx.return_value

        def from_record_ctx(record):
            if record.id == failing.id:
                raise ValueError("boom")
            return ok_ctx

        mock_factory.from_record_ctx.side_effect = from_record_ctx

        self._cron()

        self.assertFalse(failing.account_info_last_synced_at)
        self.assertGreater(failing.account_info_next_run, fields.Datetime.now())
        self.assertTrue(working.account_info_last_synced_at)
        self.assertGreater(working.account_info_next_run, fields.Datetime.now())

    def test_cron_refresh_skips_family_without_schedule(self, mock_factory):
        connection = self._make_due(make_connection(self.env, status=ConnectionStatus.ACTIVE))
        next_run = connection.account_info_next_run

        with patch(_SCHEDULE_PATH, return_value=None):
            self._cron()

        mock_factory.from_record_ctx.assert_not_called()
        self.assertEqual(connection.account_info_next_run, next_run)
            