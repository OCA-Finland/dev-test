from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from odoo.tests.common import BaseCase

from ...utils.clock import to_odoo_utc_datetime, utc_now, utc_today


class TestClock(BaseCase):

    def test_utc_today_uses_utc_date(self):
        fixed_now = datetime(2026, 11, 10, 23, 30, tzinfo=timezone.utc)
        with patch("odoo.addons.l10n_fi_bank_connectors.utils.clock.utc_now",
                   return_value=fixed_now):
            self.assertEqual(utc_today().isoformat(), "2026-11-10")

    def test_utc_now_is_aware_utc(self):
        now = utc_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset(), timedelta(0))

    def test_to_odoo_datetime_converts_offset_to_naive_utc(self):
        value = datetime(
            2026, 11, 10, 12, 0,
            tzinfo=timezone(timedelta(hours=2)),
        )

        result = to_odoo_utc_datetime(value)

        self.assertEqual(result, datetime(2026, 11, 10, 10, 0))
        self.assertIsNone(result.tzinfo)

    def test_to_odoo_datetime_rejects_naive_input(self):
        with self.assertRaises(ValueError):
            to_odoo_utc_datetime(datetime(2026, 11, 10, 12, 0))