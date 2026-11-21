from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from .....services.rest.op_corporate.constants.op_api import ACCOUNTS_PATH, ACCOUNT_DETAILS_PATH
from .....services.rest.op_corporate.op_ais import OPAIS


def _make_service():
    return OPAIS.__new__(OPAIS)


class TestGetAccounts(TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = _make_service()

    def test_empty_input(self):
        self.service._get = MagicMock(return_value=[])
        self.service._map_account = MagicMock()

        result = self.service.get_accounts()

        self.assertEqual(result, [])
        self.service._map_account.assert_not_called()

    def test_multiple_accounts(self):
        raw_accounts = [{"id": "1"}, {"id": "2"}]
        self.service._get = MagicMock(return_value=raw_accounts)
        self.service._map_account = MagicMock(side_effect=lambda a: f"mapped-{a['id']}")

        result = self.service.get_accounts()

        self.service._get.assert_called_once_with(ACCOUNTS_PATH)
        self.assertEqual(result, ["mapped-1", "mapped-2"])


class TestFilterTransactionsByBookingDate(TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = _make_service()
        self.start = date(2026, 1, 1)
        self.end = date(2026, 1, 31)

    def _tx(self, booking_date):
        return MagicMock(booking_date=booking_date)

    def _filter(self, transactions):
        return self.service.filter_transactions(transactions, self.start, self.end)

    def test_empty_input(self):
        """Test that the method returns an empty collection if there is no input."""
        self.assertEqual(self._filter([]), [])

    def test_boundaries(self):
        """Test that the lower boundary is kept and the upper boundary is dropped."""
        cases = {
            "lower boundary kept": (date(2026, 1, 1), True),
            "upper boundary dropped": (date(2026, 1, 31), False),
        }
        for label, (booking_date, kept) in cases.items():
            with self.subTest(label):
                tx = self._tx(booking_date)
                self.assertEqual(self._filter([tx]), [tx] if kept else [])

    def test_drops_out_of_range(self):
        """Test that transactions with the booking date before or after the period are dropped."""
        for label, booking_date in {
            "before range": date(2025, 12, 31),
            "after range": date(2026, 2, 1),
        }.items():
            with self.subTest(label):
                self.assertEqual(self._filter([self._tx(booking_date)]), [])

    def test_mixed_batch_keeps_only_in_range(self):
        """Test that only in-range transactions are kept (order preserved) and null booking dates are dropped."""
        first = self._tx(date(2026, 1, 10))
        second = self._tx(date(2026, 1, 15))
        others = [self._tx(date(2025, 12, 1)), self._tx(date(2026, 3, 1)), self._tx(None)]

        result = self._filter([others[0], first, others[1], others[2], second])
        self.assertEqual(result, [first, second])

class TestGetCurrentBalance(TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = _make_service()

    def test_returns_decimal_from_gross_balance(self):
        self.service._get = MagicMock(return_value={"grossBalance": "1234.56"})

        result = self.service._get_current_balance("acc-1")

        self.service._get.assert_called_once_with(ACCOUNT_DETAILS_PATH.format(surrogate_id="acc-1"))
        self.assertEqual(result, Decimal("1234.56"))


class TestGetBalanceValues(TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = _make_service()

    def test_include_balances_false_returns_empty(self):
        self.service._get_current_balance = MagicMock()

        result = self.service._get_balance_values("acc-1", include_balances=False)

        self.assertEqual(result, {})
        self.service._get_current_balance.assert_not_called()

    def test_include_balances_true_returns_balance_end_real(self):
        self.service._get_current_balance = MagicMock(return_value=Decimal("500.00"))

        result = self.service._get_balance_values("acc-1", include_balances=True)

        self.assertEqual(result, {"balance_end_real": 500.00})


class TestBuildDateRangeParams(TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = _make_service()

    def test_builds_utc_microsecond_boundaries(self):
        self.assertEqual(
            self.service._build_date_range_params(
                date(1970, 1, 2),
                date(1970, 1, 2),
            ),
            {
                "fromTimestamp": 86_400_000_000,
                "toTimestamp": 172_799_999_999,
            },
        )

    def test_omits_missing_bounds(self):
        self.assertEqual(
            self.service._build_date_range_params(None, None),
            {},
        )