from datetime import datetime, timezone, timedelta

from odoo.tests.common import BaseCase

from .....services.soap.nordea_corporate_access.nordea_ca_wsse_signing import _iso


class TestWsseTimestampFormat(BaseCase):

    def test_formats_utc_timestamp_to_milliseconds(self):
        self.assertEqual(
            _iso(datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc)),
            "2026-01-02T03:04:05.678Z",
        )

    def test_normalizes_offset_to_utc(self):
        offset = timezone(timedelta(hours=2))
        self.assertEqual(
            _iso(datetime(2026, 1, 2, 0, 30, tzinfo=offset)),
            "2026-01-01T22:30:00.000Z",
        )

    def test_rejects_naive_datetime(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            _iso(datetime(2026, 1, 2, 3, 4, 5))