from unittest.mock import Mock

from odoo.tests.common import BaseCase

from ...services.base_banking_service import BankingServiceBase


class TestBankingServiceBaseRefresh(BaseCase):

    def test_refresh_accounts_defaults_to_get_accounts(self):
        service = Mock()
        service.get_accounts.return_value = ["dto"]

        result = BankingServiceBase.refresh_accounts(service)

        self.assertEqual(result, ["dto"])
        service.get_accounts.assert_called_once_with()