import requests

from odoo import _

from .constants.nordea_api import ACCOUNTS_PATH, TRANSACTIONS_PATH
from ...dtos import AccountDTO
from ...error_handling.error_types import BankingAPIError


class NordeaAIS:
    """Handles Account Information Service (AIS) operations for the Nordea Business API."""
    def get_accounts(self) -> list[AccountDTO]:
        """Fetch a list of accounts from Nordea."""
        data = self._http.get(ACCOUNTS_PATH)
        accounts = data.get("response", {}).get("accounts", [])
        return [self._map_account(acc) for acc in accounts]

    def _build_date_range_params(self, date_from, date_to) -> dict:
        """
        Dates refer to the booking_date, though according to Nordea docs, the date might change:
        "A booking_date may vary depending on whether the transaction is temporarily posted to the account at weekends (or after business hours) 
        or permanently posted to the account after weekend on next banking day (during following night)."
        """
        params = {}
        if date_from:
            params["from_date"] = date_from.isoformat()
        if date_to:
            params["to_date"] = date_to.isoformat()
        return params

    def _transaction_fetch_config(self, account_id: str) -> dict:
        return {
            "url": TRANSACTIONS_PATH.format(account_id=account_id),
            "get_next_token": lambda data: data.get("response", {}).get("continuation_key"),
            "set_next_token": lambda params, token: params.update({"continuation_key": token}),
        }
    
    def build_statement_values(self, transaction_dtos):
        """Identify balance_before and balance_end_real values from the previous statement ending balance."""
        if not transaction_dtos:
            return {}

        ordered = sorted(transaction_dtos, key=lambda t: t.booking_date)
        stmt_date = ordered[0].booking_date

        batch_net_amount = sum(float(t.amount) for t in ordered if t.amount is not None)
        journal = getattr(self, 'journal_id', None)

        balance_start = 0.0
        if journal:
            prev_statement = self.env['account.bank.statement'].search([
                ('journal_id', '=', journal.id),
                ('date', '<', stmt_date)
            ], order='date desc, id desc', limit=1)

            if prev_statement:
                balance_start = float(prev_statement.balance_end_real)

        return {
            "balance_start": balance_start,
            "balance_end_real": balance_start + batch_net_amount,
        }

    def _get_transactions_from_response(self, data: dict) -> list:
        """Extract transactions from the API response data."""
        return data.get("response", {}).get("transactions", [])
    
    def _get(self, url: str, params: dict = None) -> dict:
        return self._http.get(url, params=params)
