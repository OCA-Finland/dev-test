from datetime import date, datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

def _to_microseconds(dt: datetime) -> int:
    delta = dt - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def to_start_of_day_microseconds(d: date) -> int:
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return _to_microseconds(dt)


def to_end_of_day_microseconds(d: date) -> int:
    next_midnight = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
    return _to_microseconds(next_midnight - timedelta(microseconds=1))
