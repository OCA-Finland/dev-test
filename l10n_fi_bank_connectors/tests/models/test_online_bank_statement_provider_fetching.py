from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class TestOnlineBankStatementProviderFetching(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        _SERVICES_PATH = 'odoo.addons.l10n_fi_bank_connectors.models.online_bank_statement_provider.OnlineBankStatementProvider._get_available_services'

        journal = cls.env["account.journal"].create({
            "name": "Test Bank Journal",
            "type": "bank",
            "code": "TBNK",
        })

        with patch(_SERVICES_PATH, return_value=[("mock", "Mock Provider")]):
            cls.provider = cls.env["online.bank.statement.provider"].create({
                "name": "Test Provider",
                "journal_id": journal.id,
                "service": "mock",
                "create_statement": True,
                "statement_creation_mode": "daily",
            })
            cls.env.flush_all()

        cls.banking_account = MagicMock()
        cls.banking_account.external_account_id = "acc-1"
        cls.banking_account.iban = "FI2112345600000785"
        cls.banking_account.name = "Test Account"

    def _run_max_pages_test(self, max_pages):
        service = MagicMock()
        service.max_transaction_pages = max_pages
        service.get_transactions.return_value = []

        self.provider._fetch_transaction_dtos(
            service,
            self.banking_account,
            "2026-01-01",
            "2026-01-31",
        )

        service.get_transactions.assert_called_once_with(
            account_id="acc-1",
            date_from="2026-01-01",
            date_to="2026-01-31",
            max_pages=max_pages,
        )

    def test_op_sandbox_passes_max_pages(self):
        """
        OP sandbox has API pagination limit configured.
        Provider must pass max_transaction_pages to the service.
        """
        self._run_max_pages_test(10)

    def test_services_without_max_pages_do_not_fail(self):
        """
        Services without max_transaction_pages configuration
        must still work.
        """
        service = MagicMock()
        service.max_transaction_pages = None
        service.get_transactions.return_value = []

        self.provider._fetch_transaction_dtos(
            service,
            self.banking_account,
            "2026-01-01",
            "2026-01-31",
        )

        service.get_transactions.assert_called_once_with(
            account_id="acc-1",
            date_from="2026-01-01",
            date_to="2026-01-31",
            max_pages=None,
        )
