import json
import logging

from datetime import date
from lxml import etree

from .constants.nordea_response_codes import RESPONSE_CODES_OK_OR_NO_CONTENT, NordeaResponseCode
from .constants.nordea_ws import (
    COMMAND_DOWNLOAD_FILE_LIST,
    COMMAND_DOWNLOAD_FILE,
    COMMAND_GET_USER_INFO,
    ENVIRONMENT_PRODUCTION,
    SOFTWARE_ID,
    FileStatus
)
from .constants.soap_envelope import TAG_DOWNLOAD_FILE_LIST_IN, TAG_DOWNLOAD_FILE_IN, TAG_GET_USER_INFO_IN
from ...dtos import AccountDTO
from ...error_handling.error_types import AccountRefreshNotSupported
from ...error_handling.soap_error_types import BankingProtocolError
from .nordea_ca_dtos import ApplicationRequestDTO, ApplicationResponseDTO
from .nordea_ca_response_parser import parse_application_response, parse_file_descriptors
from ....utils.clock import utc_now
from ....utils.formatting import to_decimal

BODY_TAG_BY_COMMAND = {
    COMMAND_DOWNLOAD_FILE_LIST: TAG_DOWNLOAD_FILE_LIST_IN,
    COMMAND_DOWNLOAD_FILE: TAG_DOWNLOAD_FILE_IN,
    COMMAND_GET_USER_INFO: TAG_GET_USER_INFO_IN,
}

_logger = logging.getLogger(__name__)


class NordeaCorporateAccessAIS:
    """Handles AIS for Nordea Corporate Access."""

    def _parse_application_response(self, response_element) -> ApplicationResponseDTO:
        try:
            return parse_application_response(response_element)
        except BankingProtocolError as exc:
            error = exc
            cause = None
        except (TypeError, ValueError) as exc:
            error = BankingProtocolError(
                "Nordea returned a malformed ApplicationResponse"
            )
            cause = exc

        error_handler = getattr(self, "_error_handler", None)
        if error_handler:
            error_handler.handle(error)
        if cause:
            raise error from cause
        raise error

    def get_accounts(self) -> list[AccountDTO]:
        """NCA has no account-list feed, so this returns
        the already manually-registered online.banking.account records."""
        if not self._connection:
            return []
        return [self._map_account(a) for a in self._connection.bank_account_ids]

    def refresh_accounts(self) -> list[AccountDTO]:
        """NCA has no remote account feed; accounts are registered manually."""
        raise AccountRefreshNotSupported(
            "Nordea Corporate Access has no account info to refresh."
        )

    def _map_account(self, account) -> AccountDTO:
        return AccountDTO(
            external_id=account.iban,
            iban=account.iban,
            currency=account.currency_id.name if account.currency_id else "",
            name=account.name,
            raw=json.loads(account.raw_data) if account.raw_data else {},
            bic=account.bic or "",
            balance=to_decimal(account.balance),
            product=account.product or "",
        )

    # for details see: https://www.nordea.fi/Images/146-85800/Web%20Services_Service%20Description.pdf
    # for contents details see: https://www.nordea.fi/Images/146-163432/web-services-security-and-communication-description.pdf
    def _download_file_list(self,  date_from: date | None, date_to: date | None, file_type: str | None = None, status: FileStatus | str = FileStatus.NEW,):
        """Request the list of available files from Nordea."""

        request = ApplicationRequestDTO(
            customer_id=self._connection.nca_sender_id_decrypted,
            target_id=self._connection.nca_signer_id_decrypted,
            timestamp=utc_now(),
            software_id=SOFTWARE_ID,
            environment=ENVIRONMENT_PRODUCTION,
            command=COMMAND_DOWNLOAD_FILE_LIST,
            start_date=date_from,
            end_date=date_to,
            status = FileStatus(status),
            file_type=file_type,
        )
        _logger.info(
            "NCA DownloadFileList request: date_from=%s date_to=%s status=%s file_type=%s",
            date_from, date_to, FileStatus(status).value, file_type,
        )

        response_element = self._execute_application_request(request)
        response_dto = self._parse_application_response(response_element)

        code = self._check_response_code(
            response_dto, "DownloadFileList", accepted=RESPONSE_CODES_OK_OR_NO_CONTENT
        )
        if code is NordeaResponseCode.CONTENT_NOT_FOUND:
            descriptors = []
        else:
            descriptors = parse_file_descriptors(response_element)
        _logger.info(
            "NCA DownloadFileList response: code=%s descriptors=%d",
            response_dto.response_code, len(descriptors),
        )
        return descriptors

    def _download_file(self, file_reference: str):
        """Download a specific file by reference."""
        request = ApplicationRequestDTO(
            customer_id=self._connection.nca_sender_id_decrypted,
            target_id=self._connection.nca_signer_id_decrypted,
            timestamp=utc_now(),
            software_id=SOFTWARE_ID,
            environment=ENVIRONMENT_PRODUCTION,
            command=COMMAND_DOWNLOAD_FILE,
            file_references=[file_reference],
        )
        response_element = self._execute_application_request(request)
        response_dto = self._parse_application_response(response_element)

        self._check_response_code(response_dto, "DownloadFile")
        _logger.info(
            "NCA DownloadFile: ref=%s code=%s content_bytes=%d compressed=%s",
            file_reference, response_dto.response_code,
            len(response_dto.content or b""), response_dto.compressed,
        )

        return response_dto

    def _get_user_info(self):
        """Request user/service info from Nordea — used as a lightweight auth probe."""
        request = ApplicationRequestDTO(
            customer_id=self._connection.nca_sender_id_decrypted,
            target_id=self._connection.nca_signer_id_decrypted,
            timestamp=utc_now(),
            software_id=SOFTWARE_ID,
            environment=ENVIRONMENT_PRODUCTION,
            command=COMMAND_GET_USER_INFO,
        )
        response_element = self._execute_application_request(request)
        _logger.warning("NCA RAW RESPONSE:\n%s", etree.tostring(response_element, pretty_print=True).decode())
        return self._parse_application_response(response_element)

    def probe_auth(self) -> ApplicationResponseDTO:
        """Probe whether the configured credentials are accepted by Nordea."""
        response_dto = self._get_user_info()
        self._check_response_code(
            response_dto, "authentication probe", accepted=RESPONSE_CODES_OK_OR_NO_CONTENT
        )
        return response_dto
