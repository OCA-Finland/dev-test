import logging

from datetime import datetime, timezone
from lxml import etree
from typing import Optional

_logger = logging.getLogger(__name__)


def extract_text(parent: etree._Element, path: str, nsmap: dict) -> Optional[str]:
    """Extract and strip text from an element at the given XPath."""
    el = parent.find(path, nsmap)
    if el is not None and el.text:
        return el.text.strip()
    return None



def parse_iso_datetime(text: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp and normalize it to aware UTC."""
    if text is None or not text.strip():
        return None

    text = text.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 datetime: {text!r}") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _logger.warning("ISO 8601 datetime has no timezone; assuming UTC: %r", text)
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def parse_datetime(parent: etree._Element, path: str, nsmap: dict) -> Optional[datetime]:
    """Parse an ISO 8601 datetime element."""
    return parse_iso_datetime(extract_text(parent, path, nsmap))



def parse_bool(parent: etree._Element, path: str, nsmap: dict) -> Optional[bool]:
    """Parse a boolean element."""
    text = extract_text(parent, path, nsmap)
    if text:
        return text.lower() in ("true", "1", "yes")
    return None


def parse_float(parent: etree._Element, path: str, nsmap: dict) -> Optional[float]:
    """Parse a float element."""
    text = extract_text(parent, path, nsmap)
    if text:
        try:
            return float(text)
        except ValueError:
            pass
    return None


def parse_int(parent: etree._Element, path: str, nsmap: dict) -> Optional[int]:
    """Parse an int element."""
    text = extract_text(parent, path, nsmap)
    if text:
        try:
            return int(text)
        except ValueError:
            pass
    return None