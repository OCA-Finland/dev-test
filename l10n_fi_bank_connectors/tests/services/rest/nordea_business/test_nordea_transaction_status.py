from odoo.tests.common import BaseCase

from .....services.rest.http_paginated_transactions import HTTPPaginatedTransactions
from .....services.rest.nordea_business.constants.nordea_transactions import NordeaTransactionStatus
from .....services.rest.nordea_business.nordea_dtos import NordeaTransactionDTO
from .....services.rest.nordea_business.nordea_business_service import NordeaBusinessService
from .....utils.formatting import to_decimal


_URL = 'test://transactions'


class _TestPagedService(HTTPPaginatedTransactions):

    def __init__(self, pages, filter_status=None):
        self._pages = pages
        self._filter_status = filter_status

    def _get(self, url, params=None):
        idx = params.get('page_index', 0)
        next_idx = idx + 1 if idx + 1 < len(self._pages) else None
        return {'transactions': self._pages[idx], 'next': next_idx}

    def _get_transactions_from_response(self, data):
        return data['transactions']

# TODO only Nordea TransactionDTO has status field so using it for now; after Danske implementation probably create TestDTO
# to make the test fully independent
    def _map_transaction(self, raw) -> NordeaTransactionDTO:
        return NordeaTransactionDTO(
            amount=to_decimal(raw.get('amount', '0')),
            transaction_id=raw['id'],
            status=raw.get('status', ''),
        )

    def _should_include_transaction(self, dto) -> bool:
        if self._filter_status is None:
            return True
        return dto.status == self._filter_status

    def _get_next_token(self, data):
        return data.get('next')

    def _set_next_token(self, params, token):
        params['page_index'] = token

    def _build_date_range_params(self, date_from, date_to) -> dict:
        return {}

    def _transaction_fetch_config(self, account_id) -> dict:
        return {
            'url': _URL,
            'get_next_token': self._get_next_token,
            'set_next_token': self._set_next_token,
        }

    def get_accounts(self):
        return []

    def build_statement_values(self, transaction_dtos):
        return {}

    def initiate_payment(self, payment):
        raise NotImplementedError

    def get_payment_status(self, banking_payment_id):
        raise NotImplementedError

    def _map_account(self, raw):
        raise NotImplementedError

    @property
    def provider_name(self) -> str:
        return "test"

    def _fetch(self, account_id='acc1'):
        return self._fetch_transactions_pages(
            url=_URL,
            params={'page_index': 0},
            account_id=account_id,
            get_next_token=self._get_next_token,
            set_next_token=self._set_next_token,
        )


class TestFetchTransactionsPagesFiltering(BaseCase):

    def test_mixed_status_page_only_includes_billed(self):
        pages = [[
            {'id': 'T1', 'status': 'billed', 'amount': '10'},
            {'id': 'T2', 'status': 'reserved', 'amount': '20'},
            {'id': 'T3', 'status': 'confirmed', 'amount': '30'},
        ]]
        service = _TestPagedService(pages, filter_status='billed')

        results = service._fetch()

        self.assertEqual([r.transaction_id for r in results], ['T1'])

    def test_pagination_continues_even_when_a_page_is_fully_filtered_out(self):
        pages = [
            [{'id': 'T1', 'status': 'reserved', 'amount': '1'}],   # page 0: no billed transactions
            [{'id': 'T2', 'status': 'billed', 'amount': '2'}],     # page 1: should still be reached
        ]
        service = _TestPagedService(pages, filter_status='billed')

        results = service._fetch()

        self.assertEqual([r.transaction_id for r in results], ['T2'])

    def test_no_filter_includes_everything(self):
        pages = [[
            {'id': 'T1', 'status': 'reserved', 'amount': '1'},
            {'id': 'T2', 'status': '', 'amount': '2'},
        ]]
        service = _TestPagedService(pages, filter_status=None)

        results = service._fetch()

        self.assertEqual({r.transaction_id for r in results}, {'T1', 'T2'})


class TestNordeaShouldIncludeTransaction(BaseCase):
    """Unit tests for NordeaBusinessService's override, independent of HTTP/auth setup."""

    def _make_service(self) -> NordeaBusinessService:
        return NordeaBusinessService.__new__(NordeaBusinessService)

    def test_reserved_is_excluded(self):
        service = self._make_service()
        dto = NordeaTransactionDTO(amount=to_decimal('10'), status=NordeaTransactionStatus.RESERVED)
        self.assertFalse(service._should_include_transaction(dto))

    def test_billed_is_included(self):
        service = self._make_service()
        dto = NordeaTransactionDTO(amount=to_decimal('10'), status=NordeaTransactionStatus.BILLED)
        self.assertTrue(service._should_include_transaction(dto))

    def test_confirmed_is_included(self):
        service = self._make_service()
        dto = NordeaTransactionDTO(amount=to_decimal('10'), status=NordeaTransactionStatus.CONFIRMED)
        self.assertTrue(service._should_include_transaction(dto))
