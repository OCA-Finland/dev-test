from decimal import Decimal

from odoo.tests.common import BaseCase

from .....services.base_banking_service import TransactionDTO
from .....services.rest.op_corporate.op_mappers import OPMappers

class TestOPMappers(BaseCase):

    def setUp(self):
        super().setUp()
        self.mapper = OPMappers()

    def test_map_transaction_negative_creditor(self):
        raw = {
            "objectId": "T1",
            "amount": "-100.50",
            "currency": "EUR",
            "bookingDate": "2026-01-10",
            "valueDate": "2026-01-10",
            "creditorAccount": "FI21CRED",
            "creditorName": "Creditor Oy",
            "debtorAccount": "FI21DEBT",
            "debtorName": "Debtor Oy",
            "reference": "REF001",
        }
        dto = self.mapper._map_transaction(raw)

        self.assertIsInstance(dto, TransactionDTO)
        self.assertEqual(dto.account_number, "FI21CRED")
        self.assertEqual(dto.partner_name, "Creditor Oy")
        self.assertEqual(dto.amount, Decimal("-100.50"))

    def test_map_transaction_positive_debtor(self):
        raw = {
            "objectId": "T2",
            "amount": "200.00",
            "currency": "EUR",
            "creditorAccount": "FI21CRED",
            "creditorName": "Creditor Oy",
            "debtorAccount": "FI21DEBT",
            "debtorName": "Debtor Oy",
        }
        dto = self.mapper._map_transaction(raw)

        self.assertEqual(dto.account_number, "FI21DEBT")
        self.assertEqual(dto.partner_name, "Debtor Oy")

    def test_map_transaction_preserves_raw(self):
        raw = {"objectId": "T7", "amount": "10.00", "extra": "field"}
        dto = self.mapper._map_transaction(raw)

        self.assertEqual(dto.raw, raw)