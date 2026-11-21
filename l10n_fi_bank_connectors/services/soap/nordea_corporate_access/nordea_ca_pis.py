import logging

from datetime import date, datetime, timezone

from ...base_banking_service import PaymentRequestDTO
from .constants.nordea_ws import (
    COMMAND_UPLOAD_FILE,
    ENVIRONMENT_PRODUCTION,
    FILE_TYPE_PAIN_001,
    FILE_TYPE_PAIN_002,
    SOFTWARE_ID,
    FileStatus
)
from .nordea_ca_dtos import ApplicationRequestDTO, NordeaCAPaymentRequestDTO, NordeaCAPaymentResponseDTO
from .nordea_ca_pain002_parser import parse_pain002, is_cancellation_reply
from .nordea_ca_payment_payload import build_pain001_payload
from ...payment_id_generation import PaymentIdGen
from ...payment_reference_validation import PaymentReferenceValidation
from ....utils.clock import utc_now



_logger = logging.getLogger(__name__)


class NordeaCAPIS(PaymentIdGen, PaymentReferenceValidation):
    """Handles payment initiation and status retrieval for Nordea Corporate Access."""

    def download_payment_status_files(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Download new pain.002 files for batch payment-status processing."""
        descriptors = self._download_file_list(
            date_from,
            date_to,
            file_type=FILE_TYPE_PAIN_002,
            status=FileStatus.NEW,
        )
        return [
            {
                "descriptor": descriptor,
                "response": self._download_file(descriptor["file_reference"]),
            }
            for descriptor in descriptors
        ]

    def payment_request_dto_class(self) -> type[PaymentRequestDTO]:
        return NordeaCAPaymentRequestDTO

    def extra_payment_request_kwargs(self, payment) -> dict:
        return {"end_to_end_id": payment.banking_payment_id}

    def initiate_payment(self, payment: NordeaCAPaymentRequestDTO) -> NordeaCAPaymentResponseDTO:
        """Submit a pain.001 payment via UploadFile, wrapped in Secure Envelope + WSSE."""
        self.validate_payment_reference(payment.reference)
        payload = build_pain001_payload(payment)

        request = ApplicationRequestDTO(
            customer_id=self._connection.nca_sender_id_decrypted,
            target_id=self._connection.nca_signer_id_decrypted,
            timestamp=utc_now(),
            software_id=SOFTWARE_ID,
            environment=ENVIRONMENT_PRODUCTION,
            command=COMMAND_UPLOAD_FILE,
            file_type=FILE_TYPE_PAIN_001,
            content=payload,
        )
        response_element = self._execute_application_request(request)
        response_dto = self._parse_application_response(response_element)

        self._check_response_code(response_dto, "UploadFile")

        return self._map_payment_response(response_dto)

    def parse_payment_status_files(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Parse available pain.002 files; skip bad files and cancellation replies."""
        parsed_files = []

        for item in self.download_payment_status_files(date_from, date_to):
            descriptor = item["descriptor"]
            response = item["response"]
            file_reference = descriptor.get("file_reference")

            if not response.content:
                _logger.warning(
                    "Skipping empty pain.002 file reference=%s", file_reference
                )
                continue

            try:
                report = parse_pain002(response.content)
            except (ValueError, TypeError) as exc:
                _logger.warning(
                    "Skipping malformed pain.002 file reference=%s: %s",
                    file_reference,
                    exc,
                )
                continue

            if is_cancellation_reply(report):
                _logger.info(
                    "Skipping camt.055 cancellation reply reference=%s",
                    file_reference,
                )
                continue

            parsed_files.append({"descriptor": descriptor, "report": report})

        return parsed_files