from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from odoo.tests.common import BaseCase, TransactionCase

from .....services.rest.nordea_business.nordea_ais import NordeaAIS
from .....services.soap.nordea_corporate_access.constants.nordea_response_codes import NordeaResponseCode
from .....services.soap.nordea_corporate_access.constants.nordea_ws import FileStatus
from .....services.soap.nordea_corporate_access.nordea_ca_ais import NordeaCorporateAccessAIS
from .....services.soap.nordea_corporate_access.nordea_ca_request_executor import NordeaCARequestExecutor


class _NordeaCAService(NordeaCARequestExecutor, NordeaCorporateAccessAIS):
    """Combines the mixins the way the real service does."""

AIS_MODULE = (
    "odoo.addons.l10n_fi_bank_connectors.services.soap."
    "nordea_corporate_access.nordea_ca_ais"
)

def _make_service():
    service = NordeaAIS.__new__(NordeaAIS)
    service._http = MagicMock()
    service._error_handler = MagicMock()
    return service


class TestDTO:
    def __init__(self, booking_date, amount):
        self.booking_date = booking_date
        self.amount = amount


class TestNordeaCAFileList(BaseCase):
    def setUp(self):
        super().setUp()
        self.service = _NordeaCAService()
        self.service._connection = MagicMock()
        self.service._connection.nca_sender_id_decrypted = "SENDER001"
        self.service._connection.nca_signer_id_decrypted = "SIGNER001"
        self.service._execute_application_request = MagicMock(return_value=object())

    @patch(f"{AIS_MODULE}.parse_file_descriptors", return_value=[{"file_reference": "FILE001"}])
    @patch(f"{AIS_MODULE}.parse_application_response")
    def test_defaults_to_new_and_passes_file_type(
        self, mock_parse_response, mock_parse_descriptors
    ):
        mock_parse_response.return_value = SimpleNamespace(
            response_code=NordeaResponseCode.OK,
            response_text=None,
        )
        file_type = "PAIN002_FILE_TYPE"

        result = self.service._download_file_list(
            date(2026, 1, 1),
            date(2026, 1, 31),
            file_type=file_type,
        )

        request = self.service._execute_application_request.call_args.args[0]
        self.assertEqual(request.status, "NEW")
        self.assertEqual(request.file_type, file_type)
        self.assertEqual(request.start_date, date(2026, 1, 1))
        self.assertEqual(request.end_date, date(2026, 1, 31))
        self.assertEqual(result, [{"file_reference": "FILE001"}])
        mock_parse_descriptors.assert_called_once_with(
            self.service._execute_application_request.return_value
        )

    @patch(f"{AIS_MODULE}.parse_file_descriptors", return_value=[])
    @patch(f"{AIS_MODULE}.parse_application_response")
    def test_accepts_download_file_list_statuses(
        self, mock_parse_response, _mock_parse_descriptors
    ):
        mock_parse_response.return_value = SimpleNamespace(
            response_code=NordeaResponseCode.OK,
            response_text=None,
        )

        for status in FileStatus:
            with self.subTest(status=status):
                self.service._download_file_list(None, None, status=status)
                request = self.service._execute_application_request.call_args.args[0]
                self.assertEqual(request.status, status)

    def test_rejects_unsupported_status(self):
        for status in ("INVALID", "DOWNLOADED", "new"):
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    self.service._download_file_list(None, None, status=status)

        self.service._execute_application_request.assert_not_called()

    @patch(f"{AIS_MODULE}.parse_application_response")
    def test_no_content_returns_empty_list(self, mock_parse_response):
        mock_parse_response.return_value = SimpleNamespace(
            response_code=NordeaResponseCode.CONTENT_NOT_FOUND,
            response_text=None,
        )

        result = self.service._download_file_list(None, None)

        self.assertEqual(result, [])


class TestBuildStatementValues(TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = _make_service()
        self.service.env = self.env

        self.journal = self.env['account.journal'].create({
            'name': 'Nordea Test Bank',
            'code': 'NDEA',
            'type': 'bank',
        })
        self.service.journal_id = self.journal

    def test_empty_transaction_dtos(self):
        result = self.service.build_statement_values([])
        self.assertEqual(result, {})

    def test_no_previous_statement(self):
        """Should default balance_start to 0.0."""
        dtos = [
            TestDTO(booking_date=date(2026, 7, 28), amount="100.00"),
            TestDTO(booking_date=date(2026, 7, 28), amount="-25.50"),
        ]

        result = self.service.build_statement_values(dtos)

        self.assertEqual(result["balance_start"], 0.0)
        self.assertEqual(result["balance_end_real"], 74.50)

    def test_with_previous_statement(self):
        """Should inherit balance_start from the preceding statement's balance_end_real."""
        self.env['account.bank.statement'].create({
            'name': 'BNK4/2026-07-27',
            'journal_id': self.journal.id,
            'balance_start': 0.0,
            'balance_end_real': 29.51,
            'line_ids': [(0, 0, {
                'date': date(2026, 7, 27),
                'payment_ref': 'payment 1',
                'amount': 29.51,
                'journal_id': self.journal.id,
            })],
        })

        dtos = [
            TestDTO(booking_date=date(2026, 7, 28), amount="500.00"),
            TestDTO(booking_date=date(2026, 7, 28), amount="-100.00"),
        ]

        result = self.service.build_statement_values(dtos)

        self.assertEqual(result["balance_start"], 29.51)
        self.assertEqual(result["balance_end_real"], 429.51)

    def test_selects_most_recent_previous_statement(self):
        """Should use the most recent statement."""
        self.env['account.bank.statement'].create({
            'name': 'BNK4/2026-07-25',
            'journal_id': self.journal.id,
            'balance_start': 0.0,
            'balance_end_real': 10.00,
            'line_ids': [(0, 0, {
                'date': date(2026, 7, 25),
                'payment_ref': 'payment 1',
                'amount': 10.00,
                'journal_id': self.journal.id,
            })],
        })

        self.env['account.bank.statement'].create({
            'name': 'BNK4/2026-07-27',
            'journal_id': self.journal.id,
            'balance_start': 10.00,
            'balance_end_real': 29.51,
            'line_ids': [(0, 0, {
                'date': date(2026, 7, 27),
                'payment_ref': 'payment 2',
                'amount': 19.51,
                'journal_id': self.journal.id,
            })],
        })

        self.env['account.bank.statement'].create({
            'name': 'BNK4/2026-07-29',
            'journal_id': self.journal.id,
            'balance_start': 1000.00,
            'balance_end_real': 1000.00,
            'line_ids': [(0, 0, {
                'date': date(2026, 7, 29),
                'payment_ref': 'payment 3',
                'amount': 0.00,
                'journal_id': self.journal.id,
            })],
        })

        dtos = [TestDTO(booking_date=date(2026, 7, 28), amount="100.00")]

        result = self.service.build_statement_values(dtos)

        self.assertEqual(result["balance_start"], 29.51)
        self.assertEqual(result["balance_end_real"], 129.51)