import json

from datetime import datetime, date

from ..services.base_banking_service import TransactionDTO


def _to_date(value) -> date:
    """Convert a datetime to a date while preserving date values."""
    if isinstance(value, datetime):
        return value.date()
    return value

def normalize_dates(date_since, date_until) -> tuple[date, date]:
    """Normalize statement-window bounds to calendar dates."""
    return _to_date(date_since), _to_date(date_until)

def prepare_transactions_for_statements(dto: TransactionDTO) -> dict:
    """Convert a TransactionDTO to a dict for Odoo's account.bank.statement.line."""
    # parent provider expects a datetime object
    booking_date = dto.booking_date
    if isinstance(booking_date, date) and not isinstance(booking_date, datetime):
        booking_date = datetime(booking_date.year, booking_date.month, booking_date.day, 0, 0, 0)

    return {
    "unique_import_id": dto.transaction_id,
    "date": booking_date,
    "amount": dto.amount,
    "payment_ref": dto.payment_ref or "",
    "ref": dto.payment_ref,  # parent's fallback expects this key to exist
    "account_number": dto.account_number or "",
    "partner_name": dto.partner_name or "",
    "transaction_type": dto.transaction_type,
    "raw_data": json.dumps(dto.raw) if dto.raw is not None else "",
}
