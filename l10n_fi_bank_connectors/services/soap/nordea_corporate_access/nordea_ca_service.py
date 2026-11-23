import gzip
import logging

from datetime import date, datetime

from ...base_banking_service import BankingServiceBase
from .constants.nordea_ca_auth_config import PROVIDER_NAME
from .constants.nordea_ca_transactions import NordeaCATransactionStatus
from .constants.nordea_ws import ENDPOINT_PRODUCTION, FILE_TYPE_CAMT_053_EXTENDED, FileStatus
from ...dtos import TransactionDTO
from ...error_handling.nordea_ca_error_handler import NordeaCAErrorHandler
from .nordea_ca_ais import NordeaCorporateAccessAIS
from .nordea_ca_camt053_parser import parse_camt053
from .nordea_ca_mappers import NordeaCAMappers
from .nordea_ca_pis import NordeaCAPIS
from .nordea_ca_request_executor import NordeaCARequestExecutor
from .nordea_ca_ws_client import NordeaWSClient
from ....utils.formatting import normalize_iban

_logger = logging.getLogger(__name__)


def _as_date(value):
    return value.date() if isinstance(value, datetime) else value


class NordeaCorporateAccessService(NordeaCAMappers, NordeaCorporateAccessAIS, NordeaCAPIS, NordeaCARequestExecutor, BankingServiceBase):
    """Service implementation for Nordea Corporate Access."""

    def __init__(self, connection=None):
        self._connection = connection
        self._error_handler = NordeaCAErrorHandler(PROVIDER_NAME)
        self._ws_client = NordeaWSClient(ENDPOINT_PRODUCTION, self._error_handler)

    def close(self) -> None:
        self._ws_client.close()

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    def get_transactions(
        self,
        account_id: str,
        date_from: date | None = None,
        date_to: date | None = None,
        max_pages: int | None = None,
    ) -> list[TransactionDTO]:
        """Fetch and map CAMT.053 statements."""

        self._last_balance_values = {}

        contents = self._fetch_camt053(
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
        )

        entries = []
        balances = []

        since, until = _as_date(date_from), _as_date(date_to)
        requested_iban = normalize_iban(account_id)
        _logger.info(
            "NCA pull: iban=%s range=%s..%s files_downloaded=%d",
            requested_iban, since, until, len(contents),
        )
        total_entries = skipped_files = dropped_by_date = undated = 0
        for content in contents:
            parsed = parse_camt053(content)
            file_iban = parsed["account"]["iban"]
            booked_dates = [t["booking_date"] for t in parsed["transactions"] if t.get("booking_date")]
            _logger.info(
                "NCA statement: id=%s iban=%s entries=%d booking_dates=%s..%s opening=%s closing=%s",
                parsed["statement_id"], file_iban, len(parsed["transactions"]),
                min(booked_dates, default=None), max(booked_dates, default=None),
                (parsed["balances"]["opening"] or {}).get("date"),
                (parsed["balances"]["closing"] or {}).get("date"),
            )
            if file_iban != requested_iban:
                skipped_files += 1
                _logger.info("NCA skipping statement %s: IBAN %s != requested %s",
                             parsed["statement_id"], file_iban, requested_iban)
                continue
            for entry in parsed["transactions"]:
                total_entries += 1
                booked = entry.get("booking_date")
                if booked is None:
                    undated += 1
                elif (since and booked < since) or (until and booked > until):
                    dropped_by_date += 1
                    continue
                entries.append(entry)
            balances.append(parsed["balances"])
        _logger.info(
            "NCA pull result: iban=%s files_skipped_by_iban=%d entries_seen=%d "
            "dropped_by_date=%d without_booking_date=%d kept=%d",
            requested_iban, skipped_files, total_entries, dropped_by_date, undated, len(entries),
        )

        self._last_balance_values = self._extract_balance_values(balances)

        return [
            self._map_transaction(entry)
            for entry in entries
            if self._include_transaction(entry)
        ]

    def _include_transaction(self, entry: dict) -> bool:
        """Keep booked CAMT entries only."""
        return entry.get("status") == NordeaCATransactionStatus.BOOK

    def _extract_balance_values(self, balances: list[dict]) -> dict:
        """Pick balance_start from the earliest statement's opening balance and
        balance_end_real from the latest statement's closing balance, sorted by
        each balance's own reported date — file/response order is not guaranteed
        chronological."""
        openings = [b["opening"] for b in balances if b.get("opening")]
        closings = [b["closing"] for b in balances if b.get("closing")]

        result = {}
        if openings:
            earliest = min(openings, key=lambda b: b["date"])
            result["balance_start"] = earliest["amount"]
        if closings:
            latest = max(closings, key=lambda b: b["date"])
            result["balance_end_real"] = latest["amount"]
        return result
    

    def build_statement_values(self, transaction_dtos):
        return getattr(self, '_last_balance_values', {}) or {}

    def get_payment_status(self, banking_payment_id):
        raise NotImplementedError

    def _fetch_camt053(
        self,
        account_id: str,
        date_from: date | None,
        date_to: date | None,
    ) -> list[bytes]:
        """Fetch CAMT.053 statements for the account. Returns a list of decompressed CAMT XML content bytes."""
        file_descriptors = self._download_file_list(
            date_from=date_from,
            date_to=date_to,
            file_type=FILE_TYPE_CAMT_053_EXTENDED,
            status=FileStatus.ALL,
        )
        for desc in file_descriptors:
            _logger.debug(
                "NCA descriptor: ref=%s type=%s status=%s target_id=%s",
                desc.get("file_reference"), desc.get("file_type"),
                desc.get("status"), desc.get("target_id"),
            )

        selected_references = [
            desc["file_reference"]
            for desc in file_descriptors
            if desc.get("file_type") == FILE_TYPE_CAMT_053_EXTENDED
        ]
        _logger.info(
            "NCA selected %d of %d descriptors (expected type=%s)",
            len(selected_references), len(file_descriptors), FILE_TYPE_CAMT_053_EXTENDED,
        )

        if not selected_references:
            return []

        contents = []
        for file_reference in selected_references:
            response_dto = self._download_file(file_reference)
            if response_dto.content:
                content = response_dto.content
                if response_dto.compressed and response_dto.compression_method:
                    content = self._decompress(content, response_dto.compression_method)
                contents.append(content)

        return contents

    def _decompress(self, content: bytes, method: str) -> bytes:
        """Decompress content using the specified algorithm."""
        if method.upper() == "GZIP":                                # TODO extract to constants
            return gzip.decompress(content)
        raise ValueError(f"Unsupported compression method: {method}")

    def supports_status_polling(self) -> bool:
        return False
