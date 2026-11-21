import logging

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..services.constants.payments import PaymentStatus

_logger = logging.getLogger(__name__)


def parse_date(date_str) -> Optional[date]:
    """Parse a date value into a `datetime.date`. Returns None if the input can not be parsed."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(str(date_str).split("T")[0])
    except ValueError:
        _logger.warning("Unexpected date format from Nordea API: %r", date_str)
        return None

def to_decimal(val) -> Optional[Decimal]:
    """Convert a value to a Decimal."""
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        _logger.warning("Could not parse: %r to decimal.", val)
        return None

def map_status_or_unrecognized(mapping: dict, raw: str) -> str:
    """Fall back to PaymentStatus.UNRECOGNIZED when mapping payments."""
    mapped = mapping.get(raw)
    if mapped is None:
        _logger.warning("Unexpected payment status %r — defaulting to UNRECOGNIZED", raw,)
        return PaymentStatus.UNRECOGNIZED
    return mapped

def normalize_iban(iban: str) -> str:
    """Strip whitespace from an IBAN for API payloads and comparisons."""
    return (iban or "").replace(" ", "")