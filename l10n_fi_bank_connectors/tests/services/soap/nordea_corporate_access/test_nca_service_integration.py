import gzip

from datetime import date
from decimal import Decimal
from lxml import etree
from unittest.mock import Mock, patch

from odoo.exceptions import UserError
from odoo.tests.common import BaseCase

from .....services.error_handling.error_types import AccountRefreshNotSupported
from .....services.soap.nordea_corporate_access.nordea_ca_service import NordeaCorporateAccessService
from ....test_utils import generate_self_signed_keypair
from ....utils.test_nca_fixtures import (
    _minimal_camt053_xml,
    _file_content_response,
    _file_list_response,
    _error_response,
)

class TestNordeaCAServiceIntegration(BaseCase):
    """End-to-end integration tests for Nordea CA service."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_key_pem, cls.cert_pem = generate_self_signed_keypair()

    def setUp(self):
        super().setUp()
        self.mock_connection = Mock()
        self.mock_connection.id = 1
        self.mock_connection.api_backend = "nordea_corporate_access"
        self.mock_connection.nca_sender_id_decrypted = "SENDER001"
        self.mock_connection.nca_signer_id_decrypted = "5780860238"
        self.mock_connection.nca_cert_pem_decrypted = self.cert_pem
        self.mock_connection.nca_key_pem_decrypted = self.private_key_pem
        self.mock_connection.bank_account_ids = []

        self.service = NordeaCorporateAccessService(connection=self.mock_connection)

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_get_transactions_full_pipeline(self, mock_send):
        """Test full pipeline: file list → download → parse → map → return transactions."""
        camt = _minimal_camt053_xml("FI1234567890123456", entries=[("100.00", "DBIT")])
        mock_send.side_effect = [
            etree.fromstring(_file_list_response([("FILE001", "FI1234567890123456")])),
            etree.fromstring(_file_content_response(camt)),
        ]

        transactions = self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30)
        )

        assert len(transactions) > 0
        # First transaction is the DBIT of 100.00 -> parser flips sign negative
        assert transactions[0].amount == Decimal("-100.00")

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_get_transactions_filters_by_statement_iban(self, mock_send):
        """Statements of other accounts are downloaded but ignored, matched by IBAN inside the file."""
        own = _minimal_camt053_xml(
            "FI1234567890123456",
            balances=[("OPBD", "100.00", "2026-09-01"), ("CLBD", "90.00", "2026-09-01")],
        )
        other = _minimal_camt053_xml(
            "FI9999999999999999",
            balances=[("OPBD", "700.00", "2026-09-01"), ("CLBD", "650.00", "2026-09-01")],
        )
        mock_send.side_effect = [
            etree.fromstring(_file_list_response([
                ("FILE001", "SIGNER1"),
                ("FILE002", "SIGNER1"),
            ])),
            etree.fromstring(_file_content_response(own)),
            etree.fromstring(_file_content_response(other)),
        ]

        self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
        )

        self.assertEqual(mock_send.call_count, 3)  # list + both files downloaded
        values = self.service.build_statement_values([])
        self.assertEqual(values["balance_start"], Decimal("100.00"))
        self.assertEqual(values["balance_end_real"], Decimal("90.00"))

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_get_transactions_handles_compression(self, mock_send):
        """Test that compressed file content is decompressed."""
        camt_content = _minimal_camt053_xml("FI1234567890123456")
        compressed = gzip.compress(camt_content)

        mock_send.side_effect = [
            etree.fromstring(_file_list_response([("FILE001", "FI1234567890123456")])),
            etree.fromstring(_file_content_response(compressed, compressed=True, compression_method="GZIP")),
        ]

        contents = self.service._fetch_camt053(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30)
        )

        assert len(contents) == 1
        assert contents[0] == camt_content

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_build_statement_values_single_statement(self, mock_send):
        camt = _minimal_camt053_xml(
            "FI1234567890123456",
            balances=[("OPBD", "500.50", "2026-09-01"), ("CLBD", "491.49", "2026-09-01")],
        )
        mock_send.side_effect = [
            etree.fromstring(_file_list_response([("FILE001", "FI1234567890123456")])),
            etree.fromstring(_file_content_response(camt)),
        ]

        transactions = self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 1),
        )
        values = self.service.build_statement_values(transactions)

        self.assertEqual(values["balance_start"], Decimal("500.50"))
        self.assertEqual(values["balance_end_real"], Decimal("491.49"))

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_build_statement_values_multiple_statements_sorted_by_balance_date(self, mock_send):
        # Files returned out of chronological order (day 2 before day 1).
        camt_day2 = _minimal_camt053_xml(
            "FI1234567890123456",
            balances=[("OPBD", "600.00", "2026-09-02"), ("CLBD", "650.00", "2026-09-02")],
        )
        camt_day1 = _minimal_camt053_xml(
            "FI1234567890123456",
            balances=[("OPBD", "500.00", "2026-09-01"), ("CLBD", "600.00", "2026-09-01")],
        )
        mock_send.side_effect = [
            etree.fromstring(_file_list_response([
                ("FILE_DAY2", "FI1234567890123456"),
                ("FILE_DAY1", "FI1234567890123456"),
            ])),
            etree.fromstring(_file_content_response(camt_day2)),
            etree.fromstring(_file_content_response(camt_day1)),
        ]

        transactions = self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 2),
        )
        values = self.service.build_statement_values(transactions)

        # Earliest opening (day 1), latest closing (day 2) — regardless of fetch order.
        self.assertEqual(values["balance_start"], Decimal("500.00"))
        self.assertEqual(values["balance_end_real"], Decimal("650.00"))

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_build_statement_values_missing_opening_balance(self, mock_send):
        camt = _minimal_camt053_xml(
            "FI1234567890123456",
            balances=[("CLBD", "491.49", "2026-09-01")],
        )
        mock_send.side_effect = [
            etree.fromstring(_file_list_response([("FILE001", "FI1234567890123456")])),
            etree.fromstring(_file_content_response(camt)),
        ]

        transactions = self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 1),
        )
        values = self.service.build_statement_values(transactions)

        self.assertNotIn("balance_start", values)
        self.assertEqual(values["balance_end_real"], Decimal("491.49"))

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_build_statement_values_missing_closing_balance(self, mock_send):
        camt = _minimal_camt053_xml(
            "FI1234567890123456",
            balances=[("OPBD", "500.50", "2026-09-01")],
        )
        mock_send.side_effect = [
            etree.fromstring(_file_list_response([("FILE001", "FI1234567890123456")])),
            etree.fromstring(_file_content_response(camt)),
        ]

        transactions = self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 1),
        )
        values = self.service.build_statement_values(transactions)

        self.assertNotIn("balance_end_real", values)
        self.assertEqual(values["balance_start"], Decimal("500.50"))

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_build_statement_values_no_files_returns_empty(self, mock_send):
        # Descriptor's target_id doesn't match the requested account -> filtered out.
        mock_send.return_value = etree.fromstring(
            _file_list_response([("FILE001", "FI9999999999999999")])
        )

        transactions = self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 1),
        )
        values = self.service.build_statement_values(transactions)

        self.assertEqual(values, {})

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_get_transactions_does_not_leak_stale_balance_values(self, mock_send):
        camt = _minimal_camt053_xml(
            "FI1234567890123456",
            balances=[("OPBD", "500.50", "2026-09-01"), ("CLBD", "491.49", "2026-09-01")],
        )
        other_camt = _minimal_camt053_xml(
            "FI9999999999999999",
            balances=[("OPBD", "700.00", "2026-09-02"), ("CLBD", "650.00", "2026-09-02")],
        )
        mock_send.side_effect = [
            etree.fromstring(_file_list_response([("FILE001", "FI1234567890123456")])),
            etree.fromstring(_file_content_response(camt)),
            # Second call: the only file belongs to another account.
            etree.fromstring(_file_list_response([("FILE002", "FI9999999999999999")])),
            etree.fromstring(_file_content_response(other_camt)),
        ]

        self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 1),
        )
        first_values = self.service.build_statement_values([])
        self.assertEqual(first_values["balance_start"], Decimal("500.50"))

        self.service.get_transactions(
            account_id="FI1234567890123456",
            date_from=date(2026, 9, 2),
            date_to=date(2026, 9, 2),
        )
        second_values = self.service.build_statement_values([])

        self.assertEqual(second_values, {})

    @patch('odoo.addons.l10n_fi_bank_connectors.services.soap.nordea_corporate_access.nordea_ca_ws_client.NordeaWSClient.post_envelope')
    def test_error_response_raises(self, mock_send):
        """Test that error responses raise exceptions."""
        mock_send.return_value = etree.fromstring(
            _error_response("AUTHENTICATION_FAILURE", "Invalid certificate")
        )

        with self.assertRaises(UserError) as context:
            self.service._download_file_list(
                date_from=date(2026, 9, 1),
                date_to=date(2026, 9, 30)
            )

        assert "AUTHENTICATION_FAILURE" in str(context.exception)

    def test_refresh_accounts_not_supported(self):
        with self.assertRaises(AccountRefreshNotSupported):
            self.service.refresh_accounts()

    def test_get_accounts_returns_local_records(self):
        self.assertEqual(self.service.get_accounts(), [])