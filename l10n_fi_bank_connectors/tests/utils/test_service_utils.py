from datetime import date
from decimal import Decimal

from ...services.constants.payments import PaymentStatus
from ...utils.formatting import (
    map_status_or_unrecognized, 
    parse_date, 
    to_decimal
    )

from odoo.tests.common import TransactionCase

class TestParseDate(TransactionCase):

    def test_parse_date_valid_date(self):
        assert parse_date("2024-05-01") == date(2024, 5, 1)

    def test_parse_date_with_time(self):
        assert parse_date("2024-05-01T13:45:30") == date(2024, 5, 1)

    def test_parse_date_none(self):
        assert parse_date(None) is None

    def test_parse_date_invalid_format(self):
        assert parse_date("05/01/2024") is None

    def test_parse_date_invalid_string(self):
        assert parse_date("not-a-date") is None

    def test_parse_date_non_string_input(self):
        assert parse_date(date(2024, 5, 1)) == date(2024, 5, 1)
        
class TestToDecimal(TransactionCase):

    def test_string_number(self):
        self.assertEqual(to_decimal("10.5"), Decimal("10.5"))

    def test_integer(self):
        self.assertEqual(to_decimal(10), Decimal("10"))

    def test_float(self):
        self.assertEqual(to_decimal(10.5), Decimal("10.5"))

    def test_decimal_input(self):
        self.assertEqual(to_decimal(Decimal("3.14")), Decimal("3.14"))

    def test_invalid_string(self):
        self.assertIsNone(to_decimal("invalid"))

    def test_none_input(self):
        self.assertIsNone(to_decimal(None))

    def test_empty_string(self):
        self.assertIsNone(to_decimal(""))

class TestMapStatusOrUnrecognized(TransactionCase):

    def setUp(self):
        super().setUp()
        self.mapping = {
            "PROCESSING": PaymentStatus.PROCESSING,
            "PROCESSED": PaymentStatus.PROCESSED,
            "REJECTED": PaymentStatus.REJECTED,
        }

    def test_status_maps_correctly(self):
        result = map_status_or_unrecognized(self.mapping, "PROCESSED")
        self.assertEqual(result, PaymentStatus.PROCESSED)

    def test_status_unrecognized(self):
        with self.assertLogs(level="WARNING") as captured:
            result = map_status_or_unrecognized(self.mapping, "NEW_STATUS")
        self.assertEqual(result, PaymentStatus.UNRECOGNIZED)
        self.assertTrue(
            any("NEW_STATUS" in msg for msg in captured.output),
            "Expected the unrecognized raw status to appear in the warning log",
        )

    def test_missing_status(self):
        result = map_status_or_unrecognized(self.mapping, "")
        self.assertEqual(result, PaymentStatus.UNRECOGNIZED)

    def test_case_sensitivity_is_preserved(self):
        result = map_status_or_unrecognized(self.mapping, "processing")
        self.assertEqual(result, PaymentStatus.UNRECOGNIZED)