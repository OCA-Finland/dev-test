from unittest.mock import MagicMock
 
from odoo.tests.common import BaseCase

from ....services.error_handling.base_error_handler import BankingAPIError
from ....services.rest.nordea_business.constants.nordea_transactions import NordeaTransactionStatus
from ....services.rest.nordea_business.nordea_business_service import NordeaBusinessService
 
 
def _make_transaction(
    transaction_id="TXN001",
    status=NordeaTransactionStatus.BILLED,
    amount="100.00",
    reference="REF001",
):
    return {
        "transaction_id": transaction_id,
        "booking_date": "2026-07-01",
        "value_date": "2026-07-01",
        "transaction_type_code": "TRF",
        "counterparty_account": "FI1234567890",
        "reference": reference,
        "amount": amount,
        "currency": "EUR",
        "counterparty_name": "Test Partner",
        "status": status,
    }

def _make_page(transactions, continuation_key=None):
    response = {"transactions": transactions}
    if continuation_key:
        response["continuation_key"] = continuation_key
    return {"response": response}
 
 
class TestHTTPPaginatedTransactions(BaseCase):
 
    def setUp(self):
        self.service = NordeaBusinessService.__new__(NordeaBusinessService)
        self.service._http = MagicMock()
        self.service._error_handler = MagicMock()
 
    def test_single_page(self):
        txn = _make_transaction()
        self.service._http.get.return_value = _make_page([txn])
 
        results = self.service._fetch_transactions_pages(
            url="/accounts/acc-1/transactions",
            params={},
            account_id="acc-1",
            get_next_token=lambda data: data.get("response", {}).get("continuation_key"),
            set_next_token=lambda params, token: params.update({"continuation_key": token}),
        )
 
        self.assertEqual(self.service._http.get.call_count, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].transaction_id, "TXN001")

    def test_multi_page_pagination(self):
        page1 = _make_page([_make_transaction("TXN001")], continuation_key="tok-2")
        page2 = _make_page([_make_transaction("TXN002")])
        self.service._http.get.side_effect = [page1, page2]
 
        params = {}
        results = self.service._fetch_transactions_pages(
            url="/accounts/acc-1/transactions",
            params=params,
            account_id="acc-1",
            get_next_token=lambda data: data.get("response", {}).get("continuation_key"),
            set_next_token=lambda params, token: params.update({"continuation_key": token}),
        )
 
        self.assertEqual(self.service._http.get.call_count, 2)
        self.assertEqual([dto.transaction_id for dto in results], ["TXN001", "TXN002"])
        # second call's params should carry the continuation_key from page 1
        second_call_kwargs = self.service._http.get.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get("params", {}).get("continuation_key"), "tok-2")

    def test_filters_transactions(self):
        billed = _make_transaction("TXN001", status=NordeaTransactionStatus.BILLED)
        pending = _make_transaction("TXN002", status=NordeaTransactionStatus.RESERVED)
        self.service._http.get.return_value = _make_page([billed, pending])
 
        results = self.service._fetch_transactions_pages(
            url="/accounts/acc-1/transactions",
            params={},
            account_id="acc-1",
            get_next_token=lambda data: data.get("response", {}).get("continuation_key"),
            set_next_token=lambda params, token: params.update({"continuation_key": token}),
        )
 
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].transaction_id, "TXN001")

    def test_empty_page(self):
        page1 = _make_page([], continuation_key="tok-2")
        page2 = _make_page([_make_transaction("TXN001")])
        self.service._http.get.side_effect = [page1, page2]
 
        results = self.service._fetch_transactions_pages(
            url="/accounts/acc-1/transactions",
            params={},
            account_id="acc-1",
            get_next_token=lambda data: data.get("response", {}).get("continuation_key"),
            set_next_token=lambda params, token: params.update({"continuation_key": token}),
        )
 
        self.assertEqual(self.service._http.get.call_count, 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].transaction_id, "TXN001")

    def test_banking_api_error(self):
        api_error = BankingAPIError(400, "bad request", {})
        self.service._http.get.side_effect = api_error
 
        with self.assertRaises(BankingAPIError):
            self.service._fetch_transactions_pages(
                url="/accounts/acc-1/transactions",
                params={},
                account_id="acc-1",
                get_next_token=lambda data: data.get("response", {}).get("continuation_key"),
                set_next_token=lambda params, token: params.update({"continuation_key": token}),
            )
 
        self.service._error_handler.handle.assert_not_called()
        