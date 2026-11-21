import uuid

from datetime import datetime, timezone

from ...constants.connection import cache_key
from .constants.nordea_response_codes import NordeaResponseCode
from .constants.nordea_ws import (
    COMMAND_DOWNLOAD_FILE_LIST,
    COMMAND_DOWNLOAD_FILE,
    COMMAND_GET_USER_INFO,
    COMMAND_UPLOAD_FILE,
    LANGUAGE,
    RECEIVER_ID,
    USER_AGENT,
)
from .constants.soap_envelope import (
    TAG_DOWNLOAD_FILE_LIST_IN,
    TAG_DOWNLOAD_FILE_IN,
    TAG_GET_USER_INFO_IN,
    TAG_UPLOAD_FILE_IN,
)
from ...error_handling.soap_error_types import BankingResponseCodeError
from .nordea_ca_application_request import build_application_request, sign_application_request
from .nordea_ca_cert_cache import get_or_create_cert_files
from .nordea_ca_dtos import ApplicationRequestDTO, RequestHeaderDTO
from .nordea_ca_envelope import build_envelope
from .nordea_ca_wsse_signing import sign_envelope
from ....utils.clock import utc_now

BODY_TAG_BY_COMMAND = {
    COMMAND_DOWNLOAD_FILE_LIST: TAG_DOWNLOAD_FILE_LIST_IN,
    COMMAND_DOWNLOAD_FILE: TAG_DOWNLOAD_FILE_IN,
    COMMAND_GET_USER_INFO: TAG_GET_USER_INFO_IN,
    COMMAND_UPLOAD_FILE: TAG_UPLOAD_FILE_IN,
}


class NordeaCARequestExecutor:
    """
    Builds and signs Nordea Corporate Access ApplicationRequests (inner
    ApplicationRequest signature + outer WSSE envelope signature) and hands
    them to self._ws_client for sending. Used by both AIS and PIS.
    """

    def _execute_application_request(self, request: ApplicationRequestDTO):
        """Build, sign, and send the ApplicationRequest."""

        app_request_xml = build_application_request(request)

        cert_path, key_path = get_or_create_cert_files(
            cache_key=cache_key(self._connection),
            cert_pem=self._connection.nca_cert_pem_decrypted,
            key_pem=self._connection.nca_key_pem_decrypted,
        )

        with open(cert_path, 'r') as f:
            cert_pem = f.read()
        with open(key_path, 'r') as f:
            key_pem = f.read()

        signed_app_request = sign_application_request(app_request_xml, key_pem, cert_pem)

        header = RequestHeaderDTO(
            sender_id=self._connection.nca_sender_id_decrypted,
            request_id=self._generate_request_id(),
            timestamp=utc_now(),
            receiver_id=RECEIVER_ID,
            language=LANGUAGE,
            user_agent=USER_AGENT,
        )
        envelope = build_envelope(BODY_TAG_BY_COMMAND[request.command], header, signed_app_request)
        envelope = sign_envelope(envelope, cert_pem, key_pem)

        return self._ws_client.post_envelope(envelope, (cert_path, key_path))

    def _raise_application_response_error(self, response_dto, operation: str) -> None:
        code = response_dto.response_code or "UNKNOWN"
        message = response_dto.response_text or f"{operation} failed"
        error = BankingResponseCodeError(code, message)
        self._error_handler.handle(error)
        raise error

    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        return str(uuid.uuid4())

    def _check_response_code(
        self,
        response_dto,
        operation: str,
        accepted: tuple[NordeaResponseCode, ...] = (NordeaResponseCode.OK,),
        ) -> NordeaResponseCode:
            """Return the response code member, or raise via the error handler if not accepted."""
            code = NordeaResponseCode.from_code(response_dto.response_code)
            if code not in accepted:
                self._raise_application_response_error(response_dto, operation)
            return code