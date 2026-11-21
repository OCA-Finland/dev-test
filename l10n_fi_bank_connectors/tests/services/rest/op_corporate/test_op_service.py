import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from decimal import Decimal
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from .....services.constants.http import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS
from .....services.constants.payments import PaymentStatus
from .....services.rest.op_corporate.op_dtos import OPPaymentRequestDTO, OPPaymentResponseDTO
from .....services.rest.op_corporate.op_service import OPCorporateService


def _generate_signing_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

def _make_payment_dto(**overrides) -> OPPaymentRequestDTO:
    defaults = dict(
        creditor_name="Testi Yritys Oy",
        creditor_iban="FI2112345600000785",
        debtor_iban="FI4212345600000786",
        debtor_name="Maksaja Oy",
        amount=Decimal("100.00"),
        currency="EUR",
        reference="RF481234567890",
        instruction_id="TESTINSTR001",
    )
    defaults.update(overrides)
    return OPPaymentRequestDTO(**defaults)

def _mock_response(status_code=200, json_data=None, content=b'{}'):
    r = MagicMock()
    r.status_code = status_code
    r.ok = status_code < 400
    r.content = content
    r.json.return_value = json_data if json_data is not None else {}
    r.request = MagicMock()
    r.raise_for_status = MagicMock()
    return r

_AUTH_PATH = 'odoo.addons.l10n_fi_bank_connectors.services.rest.op_corporate.op_service.OPAuth'
_SESSION_PATH = 'odoo.addons.l10n_fi_bank_connectors.services.rest.op_corporate.op_http.requests.Session'


@patch(_AUTH_PATH)
class TestCorporateService(TransactionCase):

    def setUp(self):
        super().setUp()
        self.signing_key_pem = _generate_signing_key_pem()

    def _make_service(self, mock_auth_class, signing_key_pem=None, signing_kid='test-kid-001'):
        mock_auth = MagicMock()
        mock_auth.base_url = "https://mock.api.com"
        mock_auth_class.return_value = mock_auth
        service = OPCorporateService(
            env=self.env,
            client_id='mock_id',
            client_secret='mock_secret',
            cert_pem='mock_cert',
            key_pem='mock_key',
            connection=MagicMock(),
            signing_key_pem=signing_key_pem or self.signing_key_pem,
            signing_kid=signing_kid,
        )
        return service, mock_auth

    def _wire_session(self, service, mock_auth, response):
        """Wire a mock response onto the service's persistent session."""
        mock_auth.get_auth_headers.return_value = {}
        mock_session = MagicMock()
        mock_session.request.return_value = response
        service._session = mock_session
        return mock_session

    @patch(_SESSION_PATH)
    def test_get_accounts_returns_dtos(self, mock_session_class, mock_auth_class):
        """get_accounts returns one AccountDTO per API entry."""
        service, mock_auth = self._make_service(mock_auth_class)
        api_data = [{"surrogateId": "S1", "iban": "FI42", "name": "Main Account", "currency": "EUR"}]
        mock_session = self._wire_session(service, mock_auth, _mock_response(json_data=api_data))

        accounts = service.get_accounts()

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].external_id, "S1")
        self.assertEqual(accounts[0].iban, "FI42")
        self.assertEqual(accounts[0].name, "Main Account")
        self.assertEqual(
            mock_session.request.call_args.kwargs['timeout'],
            (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )

    @patch(_SESSION_PATH)
    def test_payload_maps_dto_fields_correctly(self, mock_session_class, mock_auth_class):
        """Each DTO field maps to the correct payload field."""
        service, mock_auth = self._make_service(mock_auth_class)
        mock_session = self._wire_session(
            service, mock_auth,
            _mock_response(json_data={'instructionId': 'TESTPMT001', 'status': 'PROCESSING'})
        )

        dto = _make_payment_dto()
        service.initiate_payment(dto)

        payload = json.loads(mock_session.request.call_args.kwargs['data'])
        self.assertEqual(payload['creditor']['iban'], dto.creditor_iban.replace(' ', ''))
        self.assertEqual(payload['creditor']['name'], dto.creditor_name)
        self.assertEqual(payload['debtor']['iban'], dto.debtor_iban.replace(' ', ''))
        self.assertEqual(payload['debtor']['name'], dto.debtor_name)
        self.assertEqual(payload['instructedAmount']['amount'], f"{dto.amount:.2f}")
        self.assertEqual(payload['instructedAmount']['currency'], dto.currency)
        self.assertEqual(payload['instructionId'], dto.instruction_id)
        self.assertEqual(payload['reference'], dto.reference)


    def test_initiate_payment_sets_signature_header(self, mock_auth_class):
        """X-Req-Signature must be sent in the headers of the payment request."""
        service, mock_auth = self._make_service(mock_auth_class)
        mock_session = self._wire_session(
            service, mock_auth,
            _mock_response(json_data={'instructionId': 'TESTPMT001', 'status': 'PROCESSING'})
        )
        service.initiate_payment(_make_payment_dto())
        self.assertIn('X-Req-Signature', mock_session.request.call_args.kwargs['headers'])


    def test_initiate_payment_empty_response(self, mock_auth_class):
        service, mock_auth = self._make_service(mock_auth_class)
        self._wire_session(service, mock_auth, _mock_response(status_code=202, content=b''))
        result = service.initiate_payment(_make_payment_dto())
        self.assertIsInstance(result, OPPaymentResponseDTO)


    def test_payload_strips_iban_whitespace(self, mock_auth_class):
        service, mock_auth = self._make_service(mock_auth_class)
        mock_session = self._wire_session(service, mock_auth, _mock_response())
        dto = _make_payment_dto(
            creditor_iban="FI21 1234 5678 90",
            debtor_iban="FI42 9876 5432 10",
        )
        result = service.initiate_payment(dto)
        payload = json.loads(mock_session.request.call_args.kwargs['data'])
        self.assertEqual(payload['creditor']['iban'], "FI211234567890")
        self.assertEqual(payload['debtor']['iban'], "FI429876543210")
        self.assertEqual(result.status, PaymentStatus.UNRECOGNIZED)