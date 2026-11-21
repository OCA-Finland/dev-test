import json
import logging

from odoo.exceptions import UserError
from odoo import _

from ...base_banking_service import PaymentRequestDTO
from .constants.op_api import PAYMENT_STATUS_PATH
from .op_dtos import OPPaymentRequestDTO, OPPaymentResponseDTO
from .op_payment_validator import OPPaymentValidator
from .op_payment_signer import sign_request
from ...payment_id_generation import PaymentIdGen
from ....utils.formatting import normalize_iban

_logger = logging.getLogger(__name__)


class OPPIS(PaymentIdGen):
    """Handles payment initiation and status retrieval."""
    
    def initiate_payment(self, payment: OPPaymentRequestDTO) -> OPPaymentResponseDTO:
        """Initiate a payment request with signed payload."""
        if not self._signing_key_pem or not self._signing_kid:
            raise UserError(_(
                "Payment signing credentials are not configured. "
                "Please set the signing key and KID on the banking connection."
            ))
        OPPaymentValidator(payment).validate()
        payload_str = json.dumps(self._build_op_payment_payload(payment), separators=(',', ':'))
        signature = self._sign_payment_payload(payload_str)
        raw, raw_bytes = self._post_payment_with_bytes(payload_str, signature)
        response = self._map_payment_response(raw)
        response.raw_bytes = raw_bytes
        return response
    
    def get_payment_status(self, banking_payment_id: str) -> OPPaymentResponseDTO:
        """Fetch the status of a previously initiated payment."""
        if not banking_payment_id:
            raise UserError(_("banking_payment_id must not be empty."))
        data, raw_bytes = self._get_with_bytes(PAYMENT_STATUS_PATH.format(banking_payment_id=banking_payment_id))
        response = self._map_payment_response(data)
        response.raw_bytes = raw_bytes
        return response

    def payment_request_dto_class(self) -> type[PaymentRequestDTO]:
        return OPPaymentRequestDTO
    
    def extra_payment_request_kwargs(self, payment) -> dict:
        return {"instruction_id": payment.banking_payment_id}

    def _build_op_payment_payload(self, payment: PaymentRequestDTO) -> dict:
        """Build the payload for a payment request."""
        payload = {
            "instructionId": payment.instruction_id,
            "creditor": {
                "iban": normalize_iban(payment.creditor_iban),
                "name": payment.creditor_name,
            },
            "debtor": {
                "iban": normalize_iban(payment.debtor_iban),
                "name": payment.debtor_name,
            },
            "instructedAmount": {
                "amount": f"{payment.amount:.2f}",
                "currency": payment.currency,
            },
            "vopProcessingRules": payment.vop_processing_rules,
            "allowVopErrors": payment.allow_vop_errors,
        }

        reference_value = (payment.reference or "").strip()
        if reference_value:
            payload["reference"] = reference_value
        elif payment.message:
            payload["message"] = payment.message
        return payload
    
    def _sign_payment_payload(self, payload_str: str) -> str:
        """Sign the payment payload for authentication."""
        try:
            return sign_request(payload_str, self._signing_key_pem, self._signing_kid)
        except (ValueError, TypeError) as e:
            _logger.error("OP: failed to sign payment payload: %s", e, )
            raise UserError(_(
                "Failed to sign payment request. "
                "Check that your signing key and KID are valid."
            )) from e