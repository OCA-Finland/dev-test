from datetime import datetime, timezone

from odoo.tests.common import BaseCase

from .....utils.soap.nordea_ca_xml_utils import parse_iso_datetime


class TestParseIsoDatetime(BaseCase):

    def test_parses_z_timestamp_as_utc(self):
        self.assertEqual(
            parse_iso_datetime("2026-09-09T10:30:00Z"),
            datetime(2026, 9, 9, 10, 30, tzinfo=timezone.utc),
        )

    def test_normalizes_offset_across_date_boundary(self):
        self.assertEqual(
            parse_iso_datetime("2026-09-09T00:30:00+02:00"),
            datetime(2026, 9, 8, 22, 30, tzinfo=timezone.utc),
        )

    def test_assumes_utc_for_naive_timestamp(self):
        with self.assertLogs(
            "l10n_fi_bank_connectors.utils.soap.nordea_ca_xml_utils",
            level="WARNING",
        ):
            result = parse_iso_datetime("2026-09-09T10:30:00")

        self.assertEqual(
            result,
            datetime(2026, 9, 9, 10, 30, tzinfo=timezone.utc),
        )

    def test_empty_value_returns_none(self):
        self.assertIsNone(parse_iso_datetime(None))
        self.assertIsNone(parse_iso_datetime("  "))

    def test_invalid_nonempty_value_raises(self):
        with self.assertRaisesRegex(ValueError, "Invalid ISO 8601 datetime"):
            parse_iso_datetime("not-a-timestamp")