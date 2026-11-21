from dataclasses import dataclass

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class BackendSchedule:
    run_hour: int
    run_minute: int
    tz_name: str = "Europe/Helsinki"


BACKEND_SCHEDULES = {
    "op_corporate": BackendSchedule(1, 0),
    "nordea_business": BackendSchedule(1, 0),
    "nordea_corporate_access": BackendSchedule(8, 0),
}


def schedule_for_family(family):
    return BACKEND_SCHEDULES.get(family)

def next_daily_run(schedule, after):
    zone = ZoneInfo(schedule.tz_name)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)

    local_after = after.astimezone(zone)
    candidate = datetime.combine(
        local_after.date(),
        time(schedule.run_hour, schedule.run_minute),
        tzinfo=zone,
    )

    if candidate <= local_after:
        candidate += timedelta(days=1)

    return candidate.astimezone(timezone.utc).replace(tzinfo=None)