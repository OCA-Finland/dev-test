from datetime import datetime, timezone

from odoo.tests.common import BaseCase

from ...services.constants.backend_schedules import BackendSchedule, next_daily_run

SCHEDULE = BackendSchedule(1, 0)  # 01:00 Europe/Helsinki


class TestNextDailyRun(BaseCase):

    def test_before_slot_returns_slot_of_same_local_day(self):
        # 00:30 local on 2026-01-10 (UTC+2)
        result = next_daily_run(SCHEDULE, datetime(2026, 1, 9, 22, 30))
        self.assertEqual(result, datetime(2026, 1, 9, 23, 0))

    def test_after_slot_returns_next_day(self):
        # 12:00 local on 2026-01-10
        result = next_daily_run(SCHEDULE, datetime(2026, 1, 10, 10, 0))
        self.assertEqual(result, datetime(2026, 1, 10, 23, 0))

    def test_exactly_at_slot_returns_next_day(self):
        # 01:00 local on 2026-01-10
        result = next_daily_run(SCHEDULE, datetime(2026, 1, 9, 23, 0))
        self.assertEqual(result, datetime(2026, 1, 10, 23, 0))

    def test_naive_input_is_treated_as_utc(self):
        naive = next_daily_run(SCHEDULE, datetime(2026, 1, 10, 10, 0))
        aware = next_daily_run(SCHEDULE, datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(naive, aware)

    def test_spring_dst_gap_is_23_hours(self):
        # Slot 01:00 local on 2027-03-28 (UTC+2) -> next slot is in UTC+3
        result = next_daily_run(SCHEDULE, datetime(2027, 3, 27, 23, 0))
        self.assertEqual(result, datetime(2027, 3, 28, 22, 0))

    def test_autumn_dst_gap_is_25_hours(self):
        # Slot 01:00 local on 2027-10-31 (UTC+3) -> next slot is in UTC+2
        result = next_daily_run(SCHEDULE, datetime(2027, 10, 30, 22, 0))
        self.assertEqual(result, datetime(2027, 10, 31, 23, 0))