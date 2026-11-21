from datetime import date, datetime, timezone


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_today() -> date:
    """Return today's calendar date in UTC."""
    return utc_now().date()


def to_odoo_utc_datetime(value: datetime) -> datetime:
    """Convert an aware datetime to Odoo's naive-UTC datetime representation."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Expected a timezone-aware datetime.")

    return value.astimezone(timezone.utc).replace(tzinfo=None)