from datetime import date, datetime
from decimal import Decimal

from odoo.tests.common import BaseCase

from ...services.dtos import TransactionDTO
from ...services.soap.nordea_corporate_access.nordea_ca_dtos import (
    NordeaCATransactionDTO,
)


class TestTransactionDTODateContract(BaseCase):

    def test_calendar_dates_are_accepted(self):
        dto = TransactionDTO(
            amount=Decimal("1.00"),
            booking_date=date(2026, 1, 2),
            value_date=date(2026, 1, 3),
        )

        self.assertEqual(dto.booking_date, date(2026, 1, 2))
        self.assertEqual(dto.value_date, date(2026, 1, 3))

    def test_missing_dates_are_accepted(self):
        dto = TransactionDTO(amount=Decimal("1.00"))

        self.assertIsNone(dto.booking_date)
        self.assertIsNone(dto.value_date)

    def test_datetime_booking_date_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "booking_date must be a date"):
            TransactionDTO(
                amount=Decimal("1.00"),
                booking_date=datetime(2026, 1, 2),
            )

    def test_datetime_value_date_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "value_date must be a date"):
            TransactionDTO(
                amount=Decimal("1.00"),
                value_date=datetime(2026, 1, 2),
            )

    def test_provider_subclass_inherits_date_validation(self):
        with self.assertRaisesRegex(TypeError, "booking_date must be a date"):
            NordeaCATransactionDTO(
                amount=Decimal("1.00"),
                booking_date=datetime(2026, 1, 2),
            )