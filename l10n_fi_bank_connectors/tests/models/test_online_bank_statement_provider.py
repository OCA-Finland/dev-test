from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ...services.base_banking_service import TransactionDTO
from ..test_utils import patch_factory, make_connection
from ...utils import clock


_FACTORY_PATH = 'odoo.addons.l10n_fi_bank_connectors.models.online_bank_statement_provider.BankingServiceFactory'
_SERVICES_PATH = 'odoo.addons.l10n_fi_bank_connectors.models.online_bank_statement_provider.OnlineBankStatementProvider._get_available_services'


def _make_transaction_dto(transaction_id='T1', amount='100.50', payment_ref='REF001',
                          balance_after='1100.50', partner_name='Partner Corp'):
    return TransactionDTO(
        transaction_id=transaction_id,
        account_number='12345-ABC',
        amount=Decimal(amount),
        amount_currency='EUR',
        booking_date=date(2026, 1, 10),
        value_date=date(2026, 1, 10),
        payment_ref=payment_ref,
        partner_name=partner_name,
        balance_after=Decimal(balance_after) if balance_after else None,
    )

def _make_mock_service(history_limit=None, lookback_days=0, apply_lookback_to_manual_pulls=True, max_pages=None, transactions=None):
    mock_service = MagicMock()
    mock_service.TRANSACTION_HISTORY_LIMIT_DAYS = history_limit
    mock_service.TRANSACTION_LOOKBACK_DAYS = lookback_days
    mock_service.APPLY_LOOKBACK_TO_MANUAL_PULLS = apply_lookback_to_manual_pulls
    mock_service.max_transaction_pages = max_pages
    if transactions is not None:
        mock_service.get_transactions.return_value = transactions
        mock_service.filter_transactions.return_value = transactions
    return mock_service


class TestOnlineBankStatementProvider(TransactionCase):

    def setUp(self):
        super().setUp()
        clock_patcher = patch.object(
            clock,
            "utc_now",
            return_value=datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        )
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)
        self.connection = make_connection(self.env)

        self.banking_account = self.env['online.banking.account'].create({
            'name': 'Test Account',
            'connection_id': self.connection.id,
            'external_account_id': '12345-ABC',
            'iban': 'FI2112345600000785',
            'currency_id': self.env.ref('base.EUR').id,
        })

        self.bank_account = self.env['res.partner.bank'].create({
            'acc_number': 'FI2112345600000785',
            'partner_id': self.env.ref('base.main_partner').id,
        })

        self.journal = self.env['account.journal'].create({
            'name': 'Test Bank Journal',
            'type': 'bank',
            'code': 'TBNK',
            'bank_account_id': self.bank_account.id,
        })

        service_key = f"op_corporate_sandbox_{self.connection.id}"
        with patch(_SERVICES_PATH, return_value=[(service_key, 'Test Provider')]):
            self.provider = self.env['online.bank.statement.provider'].create({
                'name': 'Test Provider',
                'service': service_key,
                'journal_id': self.journal.id,
            })

        self.date_since = datetime(2026, 1, 1)
        self.date_until = datetime(2026, 1, 31)

    @patch(_FACTORY_PATH)
    def test_obtain_statement_data_success(self, mock_factory):
        """Successful fetch returns mapped transaction lines and final balance."""
        mock_service = _make_mock_service(
            transactions=[
                _make_transaction_dto('T1', '100.50', balance_after='1100.50'),
                _make_transaction_dto('T2', '-50.25', balance_after='1050.25',
                                    payment_ref='REF002'),
            ],
            max_pages=100,
        )
        mock_service.build_statement_values.return_value = {
            'balance_end_real': 1050.25
        }
        patch_factory(mock_factory, mock_service)

        lines, statement_values = self.provider._obtain_statement_data(
            self.date_since, self.date_until
        )

        mock_service.get_transactions.assert_called_once_with(
            account_id='12345-ABC',
            date_from=self.date_since.date(),
            date_to=self.date_until.date(),
            max_pages=100,
        )

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]['unique_import_id'], 'T1')
        self.assertEqual(lines[0]['amount'], 100.50)
        self.assertEqual(lines[0]['payment_ref'], 'REF001')
        self.assertEqual(lines[1]['amount'], -50.25)
        self.assertEqual(statement_values['balance_end_real'], 1050.25)

    @patch(_FACTORY_PATH)
    def test_obtain_statement_data_no_transactions(self, mock_factory):
        """API returning no transactions returns an empty result."""
        mock_service = _make_mock_service(transactions=[])
        patch_factory(mock_factory, mock_service)

        result = self.provider._obtain_statement_data(self.date_since, self.date_until)

        self.assertEqual(result, ([], {}))

    @patch(_FACTORY_PATH)
    def test_obtain_statement_data_no_account_configured(self, mock_factory):
        """No matching banking account raises UserError."""
        self.banking_account.iban = 'DE89370400440532013000'

        mock_service = _make_mock_service(transactions=[])
        patch_factory(mock_factory, mock_service)

        with self.assertRaisesRegex(
            UserError,
            "Could not find a matching bank account",
        ):
            self.provider._obtain_statement_data(
                self.date_since,
                self.date_until,
            )

    @patch(_FACTORY_PATH)
    def test_obtain_statement_data_get_transactions_fails(self, mock_factory):
        """get_transactions failure raises UserError."""
        mock_service = _make_mock_service()
        mock_service.get_transactions.side_effect = Exception("API is down")
        patch_factory(mock_factory, mock_service)

        with self.assertRaisesRegex(UserError, "Failed to fetch transactions.*API is down"):
            self.provider._obtain_statement_data(self.date_since, self.date_until)
            
    @patch(_FACTORY_PATH)
    def test_enforce_history_limit_clamps_date_scheduled(self, mock_factory):
        """Test that date_since older than the limit is silently clamped when syncing."""
        mock_service = _make_mock_service(transactions=[])
        mock_service.TRANSACTION_HISTORY_LIMIT_DAYS = 90
        patch_factory(mock_factory, mock_service)

        date_since = datetime(2025, 1, 1)
        date_until = datetime.combine(clock.utc_today(), datetime.min.time())

        self.provider.with_context(scheduled=True)._obtain_statement_data(
            date_since, date_until
        )

        call_args = mock_service.get_transactions.call_args
        self.assertIsNotNone(call_args)
        actual_date_from = call_args.kwargs['date_from']
        earliest_allowed = clock.utc_today() - relativedelta(days=90)
        self.assertEqual(actual_date_from, earliest_allowed)
            
    @patch(_FACTORY_PATH)
    def test_enforce_history_limit_manual(self, mock_factory):
        """Test that UserError is raised if date is set beyond the time limit in UI."""
        mock_service = _make_mock_service(transactions=[])
        mock_service.TRANSACTION_HISTORY_LIMIT_DAYS = 90
        patch_factory(mock_factory, mock_service)
 
        date_since = datetime(2025, 1, 1)
 
        with self.assertRaisesRegex(UserError, "cannot be more than 90 days"):
            self.provider._obtain_statement_data(date_since, self.date_until)

    @patch(_FACTORY_PATH)
    def test_minimum_lookback_widens_date_scheduled(self, mock_factory):
        """Scheduled pull widens date_since when the incremental gap is smaller than that window."""
        mock_service = _make_mock_service(transactions=[], lookback_days=7)
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today(), datetime.min.time())

        self.provider.with_context(scheduled=True)._obtain_statement_data(
            date_since, date_until
        )

        call_args = mock_service.get_transactions.call_args
        self.assertIsNotNone(call_args)
        actual_date_from = call_args.kwargs['date_from']
        expected = clock.utc_today() - relativedelta(days=7)
        self.assertEqual(actual_date_from, expected)

    @patch(_FACTORY_PATH)
    def test_minimum_lookback_not_widened_manual_when_disabled(self, mock_factory):
        """Manual pull is not widened when the backend opts out (Nordea)."""
        mock_service = _make_mock_service(transactions=[], lookback_days=7, apply_lookback_to_manual_pulls=False)
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today(), datetime.min.time())

        self.provider._obtain_statement_data(date_since, date_until)

        call_args = mock_service.get_transactions.call_args
        self.assertIsNotNone(call_args)
        actual_date_from = call_args.kwargs['date_from']
        self.assertEqual(actual_date_from, date_since.date())

    @patch(_FACTORY_PATH)
    def test_minimum_lookback_widens_date_manual_when_enabled(self, mock_factory):
        """Manual pull is widened when the backend opts in (e.g. OP)."""
        mock_service = _make_mock_service(transactions=[], lookback_days=7, apply_lookback_to_manual_pulls=True)
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today(), datetime.min.time())

        self.provider._obtain_statement_data(date_since, date_until)

        call_args = mock_service.get_transactions.call_args
        self.assertIsNotNone(call_args)
        actual_date_from = call_args.kwargs['date_from']
        expected = clock.utc_today() - relativedelta(days=7)
        self.assertEqual(actual_date_from, expected)

    @patch(_FACTORY_PATH)
    def test_minimum_lookback_does_not_narrow_larger_gap(self, mock_factory):
        """If the incremental gap is larger than the lookback window,
        date_since is left unchanged."""
        mock_service = _make_mock_service(transactions=[], lookback_days=7)
        patch_factory(mock_factory, mock_service)

        date_since = datetime(2026, 1, 1)
        date_until = datetime.combine(clock.utc_today(), datetime.min.time())

        self.provider.with_context(scheduled=True)._obtain_statement_data(
            date_since, date_until
        )

        call_args = mock_service.get_transactions.call_args
        self.assertIsNotNone(call_args)
        actual_date_from = call_args.kwargs['date_from']
        self.assertEqual(actual_date_from, date_since.date())

    @patch(_FACTORY_PATH)
    def test_op_today_booking_survives_capped_request_end(self, mock_factory):
        today = clock.utc_today()
        transaction = TransactionDTO(
            amount=Decimal("10.00"),
            transaction_id="today-transaction",
            booking_date=today,
        )
        mock_service = _make_mock_service(transactions=[transaction])
        mock_service.build_statement_values.return_value = {}
        mock_service._get_balance_values.return_value = {}
        mock_service.filter_transactions.side_effect = (
            lambda transactions, date_from, date_until: [
                dto for dto in transactions
                if dto.booking_date is not None
                and date_from <= dto.booking_date < date_until
            ]
        )
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(today, datetime.min.time())
        date_until = datetime.combine(
            today + relativedelta(days=1),
            datetime.min.time(),
        )

        lines, _ = self.provider._obtain_statement_data(date_since, date_until)

        mock_service.get_transactions.assert_called_once_with(
            account_id="12345-ABC",
            date_from=today,
            date_to=today,
            max_pages=None,
        )
        mock_service.filter_transactions.assert_called_once_with(
            [transaction], today, today + relativedelta(days=1)
        )
        self.assertEqual(
            [line["unique_import_id"] for line in lines],
            ["today-transaction"],
        )


class TestObtainStatementDataBalances(TransactionCase):

    def setUp(self):
        super().setUp()
        clock_patcher = patch.object(
            clock,
            "utc_now",
            return_value=datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        )
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)
        self.connection = make_connection(self.env)

        self.banking_account = self.env['online.banking.account'].create({
            'name': 'Test Account',
            'connection_id': self.connection.id,
            'external_account_id': '12345-ABC',
            'iban': 'FI2112345600000785',
            'currency_id': self.env.ref('base.EUR').id,
        })

        self.bank_account = self.env['res.partner.bank'].create({
            'acc_number': 'FI2112345600000785',
            'partner_id': self.env.ref('base.main_partner').id,
        })

        self.journal = self.env['account.journal'].create({
            'name': 'Test Bank Journal',
            'type': 'bank',
            'code': 'TBB2',
            'bank_account_id': self.bank_account.id,
        })

        service_key = f"op_corporate_sandbox_{self.connection.id}"
        with patch(_SERVICES_PATH, return_value=[(service_key, 'Test Provider')]):
            self.provider = self.env['online.bank.statement.provider'].create({
                'name': 'Test Provider',
                'service': service_key,
                'journal_id': self.journal.id,
            })

    @patch(_FACTORY_PATH)
    def test_include_balances_true_for_today(self, mock_factory):
        """date_until reaching today -> include_balances=True."""
        mock_service = _make_mock_service(
            transactions=[_make_transaction_dto()]
        )
        mock_service._get_balance_values.return_value = {}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(
            clock.utc_today() + relativedelta(days=1),
            datetime.min.time(),
        )

        self.provider._obtain_statement_data(date_since, date_until)

        mock_service._get_balance_values.assert_called_once_with(
            '12345-ABC', True
        )

    @patch(_FACTORY_PATH)
    def test_include_balances_false_for_historical(self, mock_factory):
        """Historical statement requests balances with include_balances=False."""
        mock_service = _make_mock_service(
            transactions=[_make_transaction_dto()]
        )
        mock_service._get_balance_values.return_value = {}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = datetime(2026, 1, 1)
        date_until = datetime(2026, 1, 31)

        self.provider._obtain_statement_data(date_since, date_until)

        mock_service._get_balance_values.assert_called_once_with(
            '12345-ABC', False
        )

    @patch(_FACTORY_PATH)
    def test_include_balances_works_with_date_object(self, mock_factory):
        """Plain date values must not prevent balance computation."""
        mock_service = _make_mock_service(
            transactions=[_make_transaction_dto()]
        )
        mock_service._get_balance_values.return_value = {}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = date(2026, 1, 1)
        date_until = date(2026, 1, 31)

        self.provider._obtain_statement_data(date_since, date_until)

        mock_service._get_balance_values.assert_called_once_with(
            '12345-ABC', False
        )

    @patch(_FACTORY_PATH)
    def test_balance_start_from_previous_statement(self, mock_factory):
        """Previous statement's balance_end_real is used as balance_start."""
        mock_service = _make_mock_service(transactions=[_make_transaction_dto()])
        mock_service._get_balance_values.return_value = {'balance_end_real': 500.0}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today() + relativedelta(days=1), datetime.min.time())

        previous_name = self.provider.make_statement_name(date_since - relativedelta(days=1))
        previous = self.env['account.bank.statement'].create({
            'name': previous_name,
            'balance_end_real': 420.0,
            'line_ids': [(0, 0, {
                'date': date_since - relativedelta(days=1),
                'payment_ref': 'seed',
                'journal_id': self.journal.id,
                'amount': 0.0,
            })],
        })

        _, statement_values = self.provider._obtain_statement_data(date_since, date_until)

        self.assertEqual(statement_values['balance_start'], 420.0)
        self.assertEqual(statement_values['balance_end_real'], 500.0)

    @patch(_FACTORY_PATH)
    def test_balance_start_unset_when_no_previous_statement(self, mock_factory):
        """No previous statement -> balance_start left unset (parent fallback applies)."""
        mock_service = _make_mock_service(transactions=[])
        mock_service._get_balance_values.return_value = {'balance_end_real': 500.0}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today() + relativedelta(days=1), datetime.min.time())

        _, statement_values = self.provider._obtain_statement_data(date_since, date_until)

        self.assertNotIn('balance_start', statement_values)

    @patch(_FACTORY_PATH)
    def test_balance_start_unset_when_previous_balance_end_real_falsy(self, mock_factory):
        """Previous statement exists but balance_end_real is unset -> balance_start left unset."""
        mock_service = _make_mock_service(transactions=[])
        mock_service._get_balance_values.return_value = {'balance_end_real': 500.0}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today() + relativedelta(days=1), datetime.min.time())

        previous_name = self.provider.make_statement_name(date_since - relativedelta(days=1))
        self.env['account.bank.statement'].create({
            'journal_id': self.journal.id,
            'name': previous_name,
        })

        _, statement_values = self.provider._obtain_statement_data(date_since, date_until)

        self.assertNotIn('balance_start', statement_values)

    @patch(_FACTORY_PATH)
    def test_include_balances_true_at_exact_today_boundary(self, mock_factory):
        """date_until's date exactly equal to today (not after) still counts as include_balances=True."""
        mock_service = _make_mock_service(transactions=[_make_transaction_dto()])
        mock_service._get_balance_values.return_value = {}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today(), datetime.min.time())

        self.provider._obtain_statement_data(date_since, date_until)

        mock_service._get_balance_values.assert_called_once_with('12345-ABC', True)

    @patch(_FACTORY_PATH)
    def test_balance_start_skips_gap_to_most_recent_statement(self, mock_factory):
        """No statement for the immediately preceding day (e.g. weekend) -> lookup
        still finds the most recent earlier statement and uses its balance_end_real."""
        mock_service = _make_mock_service(transactions=[_make_transaction_dto()])
        mock_service._get_balance_values.return_value = {'balance_end_real': 500.0}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today() + relativedelta(days=1), datetime.min.time())

        # Statement from 3 days ago -- nothing exists for the 2 days in between.
        older_name = self.provider.make_statement_name(date_since - relativedelta(days=3))
        self.env['account.bank.statement'].create({
            'name': older_name,
            'balance_end_real': 380.0,
            'line_ids': [(0, 0, {
                'date': date_since - relativedelta(days=3),
                'payment_ref': 'seed',
                'journal_id': self.journal.id,
                'amount': 0.0,
            })],
        })

        _, statement_values = self.provider._obtain_statement_data(date_since, date_until)

        self.assertEqual(statement_values['balance_start'], 380.0)

    @patch(_FACTORY_PATH)
    def test_balance_start_lookup_uses_unwidened_date_since(self, mock_factory):
        """Test that balance_start lookup uses the actual statement day
        (original_date_since), not the lookback-widened date_since used for fetching.
        """
        mock_service = _make_mock_service(
            transactions=[_make_transaction_dto()],
            lookback_days=7,
        )
        mock_service._get_balance_values.return_value = {'balance_end_real': 500.0}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        date_since = datetime.combine(clock.utc_today(), datetime.min.time())
        date_until = datetime.combine(clock.utc_today() + relativedelta(days=1), datetime.min.time())

        previous_name = self.provider.make_statement_name(date_since - relativedelta(days=1))
        self.env['account.bank.statement'].create({
            'name': previous_name,
            'balance_end_real': 420.0,
            'line_ids': [(0, 0, {
                'date': date_since - relativedelta(days=1),
                'payment_ref': 'seed',
                'journal_id': self.journal.id,
                'amount': 0.0,
            })],
        })

        _, statement_values = self.provider._obtain_statement_data(date_since, date_until)

        self.assertEqual(statement_values['balance_start'], 420.0)

    @patch(_FACTORY_PATH)
    def test_include_balances_uses_utc_today_at_context_midnight(self, mock_factory):
        mock_service = _make_mock_service(transactions=[])
        mock_service._get_balance_values.return_value = {}
        mock_service.build_statement_values.return_value = {}
        patch_factory(mock_factory, mock_service)

        fixed_now = datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)

        with patch.object(clock, "utc_now", return_value=fixed_now), patch.object(
            fields.Date,
            "context_today",
            return_value=date(2026, 1, 2),
        ):
            utc_today = clock.utc_today()
            date_since = datetime.combine(utc_today, datetime.min.time())
            date_until = datetime.combine(utc_today, datetime.min.time())

            self.provider._obtain_statement_data(date_since, date_until)

        mock_service._get_balance_values.assert_called_once_with(
            "12345-ABC", True
        )