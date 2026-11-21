from datetime import date

from odoo.tests.common import BaseCase

from ...utils.rest.timestamps import (
    to_end_of_day_microseconds,
    to_start_of_day_microseconds,
)


class TestTimestampConversion(BaseCase):

    def test_start_of_day_is_utc_midnight(self):
        self.assertEqual(
            to_start_of_day_microseconds(date(1970, 1, 2)),
            86_400_000_000,
        )

    def test_end_of_day_is_one_microsecond_before_next_midnight(self):
        day = date(1970, 1, 2)

        self.assertEqual(
            to_end_of_day_microseconds(day),
            172_799_999_999,
        )
        self.assertEqual(
            to_end_of_day_microseconds(day),
            to_start_of_day_microseconds(date(1970, 1, 3)) - 1,
        )