import logging

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .constants.op_api import (
    PAGE_SIZE, 
    ACCOUNTS_PATH, 
    TRANSACTIONS_PATH, 
    ACCOUNT_DETAILS_PATH)
from ...dtos import AccountDTO
from ....utils.formatting import to_decimal
from ....utils.rest.timestamps import to_start_of_day_microseconds, to_end_of_day_microseconds

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_logger = logging.getLogger(__name__)


class OPAIS():
    """
    Handles account and transaction retrieval from the OP Corporate API.
    
    One major issue is that OP API returns transactions based on their entry to the bank system, 
    while Odoo, including the parent modules organizes transactions based on the booking date. 
    To resolve the discrepancy, we always fetch transactions going back several days and filter out those 
    that have a booking date outside the range we need.
    """

    pull_stats: dict | None = None   # sandbox diagnostics of the latest get_transactions call, never persisted

    @staticmethod
    def _us_to_utc_str(us: int) -> str:
        return (_EPOCH + timedelta(microseconds=us)).strftime("%Y-%m-%d %H:%M:%S.%f UTC")
    
    def get_accounts(self) -> list[AccountDTO]:
        """Fetch all accounts."""
        data = self._get(ACCOUNTS_PATH)
        return [self._map_account(a) for a in data]

    def build_statement_values(self, transaction_dtos):
        """Identify balance_before and balance_end_real values from the first and last transaction balance fields."""
        return {}

    def filter_transactions(self, transaction_dtos, date_from, date_to):
        """Keep only transactions whose booking_date falls within [date_from, date_to] (also filters out transactions without booking date!)"""
        filtered = []
        missing_booking_date = 0
        out_of_range = 0
        out_of_range_dates = []
        for dto in transaction_dtos:
            if dto.booking_date is None:
                missing_booking_date += 1
                continue
            if date_from <= dto.booking_date < date_to:     # parent module: statement_date_until is exclusive, while date_until is inclusive
                filtered.append(dto)
            else:
                out_of_range += 1
                out_of_range_dates.append(dto.booking_date)

        stats = self.pull_stats
        if stats is not None:
            booking_dates = [dto.booking_date for dto in filtered]
            archive_dups = {k: n for k, n in stats["archive_ids"].items() if n > 1}
            object_dups = {k: n for k, n in stats["object_ids"].items() if n > 1}
            stats.update({
                "dto_count": len(transaction_dtos),
                "kept": len(filtered),
                "out_of_range": out_of_range,
                "missing_booking_date": missing_booking_date,
                "returned_min": min(booking_dates, default=None),
                "returned_max": max(booking_dates, default=None),
                "archive_dup_ids": len(archive_dups),
                "archive_dup_rows": sum(archive_dups.values()),
                "object_dup_ids": len(object_dups),
                "object_dup_rows": sum(object_dups.values()),
                "pulled_booking_min": min((d.booking_date for d in transaction_dtos if d.booking_date), default=None),
                "pulled_booking_max": max((d.booking_date for d in transaction_dtos if d.booking_date), default=None),
                "filtered_out_min": min(out_of_range_dates, default=None),
                "filtered_out_max": max(out_of_range_dates, default=None),
            })
            _logger.info(
                "OP pull stats: raw=%d, dtos=%d, kept=%d, out_of_range=%d, missing_booking_date=%d, "
                "archiveId duplicates=%d ids/%d rows %s, objectId duplicates=%d ids/%d rows %s",
                stats["raw_count"], len(transaction_dtos), len(filtered), out_of_range, missing_booking_date,
                len(archive_dups), sum(archive_dups.values()), sorted(archive_dups.items(), key=lambda kv: -kv[1])[:10],
                len(object_dups), sum(object_dups.values()), sorted(object_dups.items(), key=lambda kv: -kv[1])[:10],
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
        # reset stats at the start of every pull
        self.pull_stats = {
            "request_from": (params["fromTimestamp"], self._us_to_utc_str(params["fromTimestamp"])) if date_from else None,
            "request_to": (params["toTimestamp"], self._us_to_utc_str(params["toTimestamp"])) if date_to else None,
            "raw_count": 0,
            "raw_ts_min": None,
            "raw_ts_max": None,
            "archive_ids": Counter(),
            "object_ids": Counter(),
            "archive_missing": 0,
            "object_missing": 0,
        }
        return params
    
    def _transaction_fetch_config(self, account_id: str) -> dict:
        return {
            "url": TRANSACTIONS_PATH.format(surrogate_id=account_id),
            "get_next_token": lambda data: data.get("pagingToken"),
            "set_next_token": lambda params, token: params.update({"pagingToken": token}),
        }

    def _get_transactions_from_response(self, data: dict) -> list:
        """Extract transactions list from API response."""
        transactions = data.get("transactions", [])
        stats = self.pull_stats
        if stats is not None:
            for txn in transactions:
                stats["raw_count"] += 1
                ts = txn.get("timestamp")
                if ts is not None:
                    if stats["raw_ts_min"] is None or ts < stats["raw_ts_min"]:
                        stats["raw_ts_min"] = ts
                    if stats["raw_ts_max"] is None or ts > stats["raw_ts_max"]:
                        stats["raw_ts_max"] = ts
                if txn.get("archiveId") is not None:
                    stats["archive_ids"][txn["archiveId"]] += 1
                else:
                    stats["archive_missing"] += 1
                if txn.get("objectId") is not None:
                    stats["object_ids"][txn["objectId"]] += 1
                else:
                    stats["object_missing"] += 1
        return transactions

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