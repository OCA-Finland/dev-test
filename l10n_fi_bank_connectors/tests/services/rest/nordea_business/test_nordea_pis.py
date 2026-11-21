from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import BaseCase

from .....services.error_handling.base_error_handler import BankingAPIError
from .....services.rest.nordea_business.constants.nordea_api import (
    PAYMENTS_CONFIRM_PATH,
    PAYMENTS_SEPA_PATH,
    PAYMENTS_STATUS_PATH,
)
from .....services.rest.nordea_business.nordea_dtos import NordeaPaymentResponseDTO
from .....services.rest.nordea_business.nordea_pis import NordeaPIS

_VALIDATOR_PATH = (
    'odoo.addons.l10n_fi_bank_connectors.services.rest.nordea_business.nordea_pis.'
    'NordeaFIPaymentValidator'
)


class TestNordeaPISRawBytes(BaseCase):
    def setUp(self):
        super().setUp()
        self.pis = NordeaPIS()
        self.mapped = NordeaPaymentResponseDTO(status='processing')
        self.pis._http = MagicMock()
        self.pis._error_handler = MagicMock()
        self.pis._error_handler.handle.side_effect = UserError('handled')
        self.pis._build_nordea_payment_payload = MagicMock(return_value={'amount': '1.00'})
        self.pis._map_payment_response = MagicMock(return_value=self.mapped)

    @patch(_VALIDATOR_PATH)
    def test_initiate_payment_attaches_confirm_bytes(self, _validator):
        confirm_data = {'response': {'state': 'PENDING'}}
        self.pis._http.post.return_value = {'response': {'_id': 'PID1'}}
        self.pis._http.put_with_bytes.return_value = (confirm_data, b'confirm-body')

        result = self.pis.initiate_payment(MagicMock())

        self.pis._http.post.assert_called_once_with(PAYMENTS_SEPA_PATH, {'amount': '1.00'})
        self.pis._http.put_with_bytes.assert_called_once_with(
            PAYMENTS_CONFIRM_PATH,
            {'payments_ids': ['PID1'], 'authentication_method': 'MTA'},
        )
        self.pis._http.put.assert_not_called()
        self.pis._map_payment_response.assert_called_once_with(
            confirm_data, banking_payment_id='PID1', from_list=True,
        )
        self.assertIs(result, self.mapped)
        self.assertEqual(result.raw_bytes, b'confirm-body')

    @patch(_VALIDATOR_PATH)
    def test_initiate_payment_without_payment_id_skips_confirm(self, _validator):
        self.pis._http.post.return_value = {'response': {}}

        with self.assertRaises(UserError):
            self.pis.initiate_payment(MagicMock())

        self.pis._http.put_with_bytes.assert_not_called()

    @patch(_VALIDATOR_PATH)
    def test_initiate_payment_confirm_error_goes_to_error_handler(self, _validator):
        error = BankingAPIError(500, 'boom')
        self.pis._http.post.return_value = {'response': {'_id': 'PID1'}}
        self.pis._http.put_with_bytes.side_effect = error

        with self.assertRaises(UserError):
            self.pis.initiate_payment(MagicMock())

        self.pis._error_handler.handle.assert_called_once_with(error)

    def test_get_payment_status_attaches_fetched_bytes(self):
        data = {'response': {'state': 'CONFIRMED'}}
        self.pis._http.get_with_bytes.return_value = (data, b'status-body')

        result = self.pis.get_payment_status('PID1')

        self.pis._http.get_with_bytes.assert_called_once_with(
            PAYMENTS_STATUS_PATH.format(payment_id='PID1')
        )
        self.pis._http.get.assert_not_called()
        self.pis._map_payment_response.assert_called_once_with(
            data, banking_payment_id='PID1', from_list=False,
        )
        self.assertIs(result, self.mapped)
        self.assertEqual(result.raw_bytes, b'status-body')

    def test_get_payment_status_error_goes_to_error_handler(self):
        error = BankingAPIError(404, 'not found')
        self.pis._http.get_with_bytes.side_effect = error

        with self.assertRaises(UserError):
            self.pis.get_payment_status('PID1')

        self.pis._error_handler.handle.assert_called_once_with(error)

    def test_get_payment_status_empty_id_raises_without_http_call(self):
        with self.assertRaises(UserError):
            self.pis.get_payment_status('')

        self.pis._http.get_with_bytes.assert_not_called()