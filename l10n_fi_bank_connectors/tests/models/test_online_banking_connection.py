from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase

from ...services.constants.connection import ConnectionStatus
from ...services.dtos import AccountDTO
from ..test_utils import make_connection


class TestOnlineBankingConnection(TransactionCase):

    def setUp(self):
        super().setUp()
        self.connection = make_connection(self.env)
        
    def test_process_account_dtos_creates_new(self):
        """Test that new accounts are created."""
        dtos = [
            AccountDTO(external_id='acc_1', iban='FI2112345600000785', currency='EUR', name='Account 1', balance=1000),
            AccountDTO(external_id='acc_2', iban='FI1410093000123458', currency='EUR', name='Account 2', balance=2000),
        ]
        
        imported, updated = self.connection._process_account_dtos(dtos)
        
        self.assertEqual(imported, 2)
        self.assertEqual(updated, 0)
        accounts = self.env['online.banking.account'].search([
            ('connection_id', '=', self.connection.id)
        ])
        self.assertEqual(len(accounts), 2)
        
    def test_process_account_dtos_updates_existing(self):
        """Test that existing accounts get updated."""
        self.env['online.banking.account'].create({
            'connection_id': self.connection.id,
            'external_account_id': 'acc_1',
            'iban': 'FI2112345600000785',
            'name': 'Old Name',
            'balance': 500.0,
            'currency_id': self.env.ref('base.EUR').id,
        })
        dtos = [AccountDTO(external_id='acc_1', iban='FI2112345600000785', currency='EUR', name='New Name', balance=1500)]
        
        imported, updated = self.connection._process_account_dtos(dtos)
        
        self.assertEqual(imported, 0)
        self.assertEqual(updated, 1)
        
    def test_process_account_dtos_no_duplicates_on_resync(self):
        """Test that syncing the same DTOs twice will not create duplicate account records."""
        dtos = [
            AccountDTO(external_id='acc_1', iban='FI2112345600000785', currency='EUR', name='Account 1', balance=1000),
            AccountDTO(external_id='acc_2', iban='FI1410093000123458', currency='EUR', name='Account 2', balance=2000),
        ]
 
        self.connection._process_account_dtos(dtos)
        self.connection._process_account_dtos(dtos)
 
        accounts = self.env['online.banking.account'].search([
            ('connection_id', '=', self.connection.id)
        ])
        self.assertEqual(len(accounts), 2)
        
    def test_prepare_account_vals_known_currency(self):
        """Test that currency present in the res.currency table is correctly assigned"""
        dto = AccountDTO(external_id='acc_1', iban='FI2112345600000785', currency='EUR', name='Test', balance=100)
        eur = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'EUR')], limit=1)
        currency_map = {'EUR': eur}

        vals = self.connection._prepare_account_vals(dto, currency_map)

        self.assertIn('currency_id', vals)
        self.assertEqual(vals['currency_id'], eur.id)
        
    def test_prepare_account_vals_currency_not_in_map_returns_none(self):
        """Test that unknown currency key not in currency_map results in None currency_id."""
        dto = AccountDTO(external_id='acc_1', iban='FI2112345600000785', currency='XYZ', name='Test', balance=100)
        currency_map = {}

        vals = self.connection._prepare_account_vals(dto, currency_map)

        self.assertIn('currency_id', vals)
        self.assertIsNone(vals['currency_id'])

    def test_account_info_schedule_not_set_on_create(self):
        self.assertEqual(self.connection.status, ConnectionStatus.PENDING)
        self.assertFalse(self.connection.account_info_schedule_signature)
        self.assertFalse(self.connection.account_info_next_run)

    def test_account_info_schedule_set_on_activation(self):
        now = fields.Datetime.now()
        self.connection.write({'status': ConnectionStatus.ACTIVE})
        self.assertEqual(self.connection.account_info_schedule_signature, "1|0|Europe/Helsinki")
        self.assertGreater(self.connection.account_info_next_run, now)
        self.assertLessEqual(self.connection.account_info_next_run - now, timedelta(hours=25))

    def test_account_info_schedule_unchanged_by_unrelated_write(self):
        self.connection.write({'status': ConnectionStatus.ACTIVE})
        next_run = self.connection.account_info_next_run
        self.connection.write({'name': 'Renamed'})
        self.assertEqual(self.connection.account_info_next_run, next_run)

    def test_account_info_schedule_unchanged_when_already_active(self):
        self.connection.write({'status': ConnectionStatus.ACTIVE})
        next_run = self.connection.account_info_next_run
        self.connection.write({'status': ConnectionStatus.ACTIVE})
        self.assertEqual(self.connection.account_info_next_run, next_run)

    def test_account_info_schedule_follows_backend_change(self):
        self.connection.write({'api_backend': 'nordea_corporate_access_sandbox'})
        self.assertFalse(self.connection.account_info_schedule_signature)
        self.connection.write({'status': ConnectionStatus.ACTIVE})
        self.assertEqual(self.connection.account_info_schedule_signature, "8|0|Europe/Helsinki")

    def test_account_info_next_run_based_on_last_sync(self):
        connection = make_connection(
            self.env,
            name='Synced',
            account_info_last_synced_at=datetime(2026, 1, 1, 12, 0),
        )
        connection.write({'status': ConnectionStatus.ACTIVE})
        # 01:00 Helsinki (UTC+2 in January) on 2026-01-02 is 23:00 UTC on 2026-01-01
        self.assertEqual(connection.account_info_next_run, datetime(2026, 1, 1, 23, 0))