import logging

from odoo import _
from odoo.exceptions import UserError

from ...dtos import PaymentRequestDTO
from ...error_handling.error_types import BankingError
from .constants.nordea_api import (
    PAYMENTS_SEPA_PATH, 
    PAYMENTS_CONFIRM_PATH, 
    PAYMENTS_STATUS_PATH, 
    FI_SEPA_MAX_MESSAGE_LENGTH
)
from .nordea_dtos import NordeaPaymentRequestDTO, NordeaPaymentResponseDTO
from .nordea_payment_validator import NordeaFIPaymentValidator
from ...payment_reference_validation import PaymentReferenceValidation
from ....utils.formatting import normalize_iban

_logger = logging.getLogger(__name__)


class NordeaPIS(PaymentReferenceValidation):
    """Handles Payment Initiation Service operations for the Nordea Business API."""
    
    def initiate_payment(self, payment: NordeaPaymentRequestDTO) -> NordeaPaymentResponseDTO:
        """Initiate a payment through Nordea API, validate, and confirm it."""
        NordeaFIPaymentValidator(payment).validate()
        body = self._build_nordea_payment_payload(payment)
        try:
            init_data = self._http.post(PAYMENTS_SEPA_PATH, body)
        except BankingError as exc:
            self._error_handler.handle(exc)
            raise
        payment_id = init_data.get("response", {}).get("_id", "")
        if not payment_id:
            _logger.error("Nordea: payment initiation response missing payment ID: %s", init_data)
            raise UserError(_(
                "Nordea: payment was submitted but no payment ID was returned. "
                "Please check the payment log before retrying."
            ))

        confirm_body = {
            "payments_ids": [payment_id],
            "authentication_method": "MTA",
        }
        try:
            confirm_data, confirm_bytes = self._http.put_with_bytes(PAYMENTS_CONFIRM_PATH, confirm_body)
        except BankingError as exc:
            self._error_handler.handle(exc)
            raise
        response = self._map_payment_response(confirm_data, banking_payment_id=payment_id, from_list=True)
        response.raw_bytes = confirm_bytes
        return response

    def get_payment_status(self, banking_payment_id: str) -> NordeaPaymentResponseDTO:
        """Fetch the status of a payment by its banking_payment_id."""
        if not banking_payment_id:
            raise UserError(_("Payment ID must not be empty."))
        url = PAYMENTS_STATUS_PATH.format(payment_id=banking_payment_id)
        try:
            data, raw_bytes = self._http.get_with_bytes(url)
        except BankingError as exc:
            self._error_handler.handle(exc)
            raise
        response = self._map_payment_response(data, banking_payment_id=banking_payment_id, from_list=False)
        response.raw_bytes = raw_bytes
        return response
    
    # helpers
    def _build_nordea_payment_payload(self, payment) -> dict:
        """Build the payload for Nordea payment initiation."""
        body = {
            "amount": f"{payment.amount:.2f}",
            "currency": payment.currency,
            "debtor": {
                "account": {
                    "_type": "IBAN",
                    "currency": payment.currency,
                    "value": normalize_iban(payment.debtor_iban),
                },
            },
            "creditor": {
                "account": {
                    "_type": "IBAN",
                    "currency": payment.currency,
                    "value": normalize_iban(payment.creditor_iban),
                },
                "name": payment.creditor_name,
            },
        }

        reference = (payment.reference or "").strip()
        if reference:
            body["creditor"]["reference"] = {
                "value": reference,
                "_type": "RF",  # RF or Invoice for FI Sepa payments, OCR for NO Kid payments and 01, 04, 15, 71, 73 or 75 for Danish Transfer Form payments.
            }

        user_message = (payment.message or "").strip()
        if user_message:
            body["creditor"]["message"] = user_message[:FI_SEPA_MAX_MESSAGE_LENGTH]
        
        if payment.request_execution_date:
            body["requested_execution_date"] = payment.request_execution_date.isoformat()

        return body

    def payment_request_dto_class(self) -> type[PaymentRequestDTO]:
        return NordeaPaymentRequestDTO