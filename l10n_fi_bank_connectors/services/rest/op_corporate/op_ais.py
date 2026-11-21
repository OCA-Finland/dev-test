import logging

from decimal import Decimal, InvalidOperation

from .constants.op_api import (
    PAGE_SIZE, 
    ACCOUNTS_PATH, 
    TRANSACTIONS_PATH, 
    ACCOUNT_DETAILS_PATH)
from ...dtos import AccountDTO
from ....utils.formatting import to_decimal
from ....utils.rest.timestamps import to_start_of_day_microseconds, to_end_of_day_microseconds

_logger = logging.getLogger(__name__)

class OPAIS():
    """
    Handles account and transaction retrieval from the OP Corporate API.
    
    One major issue is that OP API returns transactions based on their entry to the bank system, 
    while Odoo, including the parent modules organizes transactions based on the booking date. 
    To resolve the discrepancy, we always fetch transactions going back several days and filter out those 
    that have a booking date outside the range we need.
    """
    
    def get_accounts(self) -> list[AccountDTO]:
        """Fetch all accounts."""
        data = self._get(ACCOUNTS_PATH)
        return [self._map_account(a) for a in data]

    def build_statement_values(self, transaction_dtos):
        """Identify balance_before and balance_end_real values from the first and last transaction balance fields."""
        return {}

    def filter_transactions(self, transaction_dtos, date_from, date_to):
        """
        Keep only transactions whose booking_date falls within [date_from, date_to].
        This also filters out transactions without booking date!
        """
        filtered = []
        missing_booking_date = 0
        out_of_range = 0
        for dto in transaction_dtos:
            if dto.booking_date is None:
                missing_booking_date += 1
                continue
            if date_from <= dto.booking_date < date_to:     # parent module: statement_date_until is exclusive, while date_until is inclusive
                filtered.append(dto)
            else:
                out_of_range += 1

        if missing_booking_date or out_of_range:
            _logger.info(
                "Filtered transactions by booking_date [%s, %s]: %d kept, "
                "%d outside range, %d missing booking_date",
                date_from, date_to, len(filtered), out_of_range, missing_booking_date,
            )
        return filtered

    def _base_transaction_params(self) -> dict:
        return {"pageSize": PAGE_SIZE}

    def _build_date_range_params(self, date_from, date_to) -> dict:
        """Both timestamps refer to the moment when the transaction was entered into the system, not the booking_date!"""
        params = {}
        if date_from:
            params["fromTimestamp"] = to_start_of_day_microseconds(date_from)
        if date_to:
            params["toTimestamp"] = to_end_of_day_microseconds(date_to)
        return params
    
    def _transaction_fetch_config(self, account_id: str) -> dict:
        return {
            "url": TRANSACTIONS_PATH.format(surrogate_id=account_id),
            "get_next_token": lambda data: data.get("pagingToken"),
            "set_next_token": lambda params, token: params.update({"pagingToken": token}),
        }

    def _get_transactions_from_response(self, data: dict) -> list:
        """Extract transactions list from API response."""
        return data.get("transactions", [])

    def _get_balance_values(self, account_id: str, include_balances: bool) -> dict:
        if not include_balances:
            return {}
        balance = self._get_current_balance(account_id)
        if balance is None:
            return {}
        return {"balance_end_real": float(balance)}

    def _get_current_balance(self, account_id: str) -> Decimal | None:
        """Fetch the account's current grossBalance."""
        data = self._get(ACCOUNT_DETAILS_PATH.format(surrogate_id=account_id))
        gross_balance = data.get("grossBalance")
        balance = to_decimal(gross_balance)
        if balance is None:
            raise InvalidOperation(
                f"Invalid OP grossBalance value: {gross_balance!r}"
            )
        return balance