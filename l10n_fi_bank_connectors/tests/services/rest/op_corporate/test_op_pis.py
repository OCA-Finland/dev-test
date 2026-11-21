from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import BaseCase

from .....services.rest.op_corporate.constants.op_api import PAYMENT_STATUS_PATH
from .....services.rest.op_corporate.op_dtos import OPPaymentRequestDTO, OPPaymentResponseDTO
from .....services.rest.op_corporate.op_pis import OPPIS

_MODULE = 'odoo.addons.l10n_fi_bank_connectors.services.rest.op_corporate.op_pis'
_VALIDATOR_PATH = f'{_MODULE}.OPPaymentValidator'
_SIGN_PATH = f'{_MODULE}.sign_request'
_NORMALIZE_PATH = f'{_MODULE}.normalize_iban'


class TestOPPISInitiatePayment(BaseCase):
    def setUp(self):
        super().setUp()
        self.pis = OPPIS()
        self.pis._signing_key_pem = 'key'
        self.pis._signing_kid = 'kid'
        self.mapped = OPPaymentResponseDTO(status='processing')
        self.calls = []

        self.pis._build_op_payment_payload = MagicMock(
            side_effect=lambda p: self.calls.append('build') or {'instructionId': 'I1'})
        self.pis._sign_payment_payload = MagicMock(
            side_effect=lambda s: self.calls.append('sign') or 'sig')
        self.pis._post_payment_with_bytes = MagicMock(
            side_effect=lambda s, sig: self.calls.append('post') or (
                {'paymentId': 'P1'}, b'{"paymentId": "P1"}'))
        self.pis._map_payment_response = MagicMock(
            side_effect=lambda raw: self.calls.append('map') or self.mapped)

    def _assert_nothing_downstream_called(self):
        self.pis._build_op_payment_payload.assert_not_called()
        self.pis._sign_payment_payload.assert_not_called()
        self.pis._post_payment_with_bytes.assert_not_called()
        self.pis._map_payment_response.assert_not_called()

    @patch(_VALIDATOR_PATH)
    def test_missing_signing_key_raises(self, validator):
        for value in (None, ''):
            with self.subTest(value=value):
                self.pis._signing_key_pem = value
                with self.assertRaises(UserError):
                    self.pis.initiate_payment(MagicMock())
        validator.assert_not_called()
        self._assert_nothing_downstream_called()

    @patch(_VALIDATOR_PATH)
    def test_missing_signing_kid_raises(self, validator):
        for value in (None, ''):
            with self.subTest(value=value):
                self.pis._signing_kid = value
                with self.assertRaises(UserError):
                    self.pis.initiate_payment(MagicMock())
        validator.assert_not_called()
        self._assert_nothing_downstream_called()

    @patch(_VALIDATOR_PATH)
    def test_validation_error_propagates_and_stops_flow(self, validator):
        validator.return_value.validate.side_effect = UserError('invalid')

        with self.assertRaises(UserError):
            self.pis.initiate_payment(MagicMock())

        self._assert_nothing_downstream_called()

    @patch(_VALIDATOR_PATH)
    def test_happy_path(self, validator):
        payment = MagicMock()
        validator.return_value.validate.side_effect = lambda: self.calls.append('validate')

        result = self.pis.initiate_payment(payment)

        validator.assert_called_once_with(payment)
        self.assertEqual(self.calls, ['validate', 'build', 'sign', 'post', 'map'])
        self.pis._build_op_payment_payload.assert_called_once_with(payment)
        # compact JSON, no spaces
        self.pis._sign_payment_payload.assert_called_once_with('{"instructionId":"I1"}')
        self.pis._post_payment_with_bytes.assert_called_once_with('{"instructionId":"I1"}', 'sig')
        self.pis._map_payment_response.assert_called_once_with({'paymentId': 'P1'})
        self.assertIs(result, self.mapped)
        self.assertEqual(result.raw_bytes, b'{"paymentId": "P1"}')


class TestOPPISGetPaymentStatus(BaseCase):
    def setUp(self):
        super().setUp()
        self.pis = OPPIS()
        self.mapped = OPPaymentResponseDTO(status='processing')
        self.pis._get_with_bytes = MagicMock()
        self.pis._map_payment_response = MagicMock(return_value=self.mapped)

    def test_empty_id_raises_without_http_call(self):
        for value in ('', None):
            with self.subTest(value=value):
                with self.assertRaises(UserError):
                    self.pis.get_payment_status(value)
        self.pis._get_with_bytes.assert_not_called()
        self.pis._map_payment_response.assert_not_called()

    def test_happy_path(self):
        data = {'status': 'ACCP'}
        self.pis._get_with_bytes.return_value = (data, b'{"status": "ACCP"}')

        result = self.pis.get_payment_status('BP1')

        self.pis._get_with_bytes.assert_called_once_with(
            PAYMENT_STATUS_PATH.format(banking_payment_id='BP1'))
        self.pis._map_payment_response.assert_called_once_with(data)
        self.assertIs(result, self.mapped)
        self.assertEqual(result.raw_bytes, b'{"status": "ACCP"}')


@patch(_NORMALIZE_PATH, side_effect=lambda iban: f'N:{iban}')
class TestOPPISBuildPayload(BaseCase):
    def setUp(self):
        super().setUp()
        self.pis = OPPIS()

    @staticmethod
    def _payment(**overrides):
        values = {
            'instruction_id': 'I1',
            'creditor_iban': 'CZ01',
            'creditor_name': 'Creditor',
            'debtor_iban': 'CZ02',
            'debtor_name': 'Debtor',
            'amount': Decimal('10.5'),
            'currency': 'EUR',
            'vop_processing_rules': 'RULES',
            'allow_vop_errors': True,
            'reference': None,
            'message': None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_full_payload_structure(self, _normalize):
        payload = self.pis._build_op_payment_payload(
            self._payment(reference='REF1'))

        self.assertEqual(payload, {
            'instructionId': 'I1',
            'creditor': {'iban': 'N:CZ01', 'name': 'Creditor'},
            'debtor': {'iban': 'N:CZ02', 'name': 'Debtor'},
            'instructedAmount': {'amount': '10.50', 'currency': 'EUR'},
            'vopProcessingRules': 'RULES',
            'allowVopErrors': True,
            'reference': 'REF1',
        })

    def test_reference_wins_over_message(self, _normalize):
        payload = self.pis._build_op_payment_payload(
            self._payment(reference='REF1', message='MSG'))

        self.assertEqual(payload['reference'], 'REF1')
        self.assertNotIn('message', payload)

    def test_blank_reference_falls_back_to_message(self, _normalize):
        for blank in ('   ', ''):
            with self.subTest(reference=blank):
                payload = self.pis._build_op_payment_payload(
                    self._payment(reference=blank, message='MSG'))
                self.assertEqual(payload['message'], 'MSG')
                self.assertNotIn('reference', payload)

    def test_no_reference_no_message(self, _normalize):
        for reference, message in ((None, None), ('  ', None), ('', '')):
            with self.subTest(reference=reference, message=message):
                payload = self.pis._build_op_payment_payload(
                    self._payment(reference=reference, message=message))
                self.assertNotIn('reference', payload)
                self.assertNotIn('message', payload)


class TestOPPISSignPayload(BaseCase):
    def setUp(self):
        super().setUp()
        self.pis = OPPIS()
        self.pis._signing_key_pem = 'key'
        self.pis._signing_kid = 'kid'

    @patch(_SIGN_PATH, return_value='sig')
    def test_returns_signature(self, sign):
        result = self.pis._sign_payment_payload('payload')

        self.assertEqual(result, 'sig')
        sign.assert_called_once_with('payload', 'key', 'kid')
