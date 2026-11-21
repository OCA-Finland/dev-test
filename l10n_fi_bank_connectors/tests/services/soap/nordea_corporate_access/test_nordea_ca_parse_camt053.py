import os

from datetime import date
from decimal import Decimal
from lxml import etree
from pathlib import Path

from odoo.tests.common import BaseCase

from .....services.soap.nordea_corporate_access.nordea_ca_mappers import NordeaCAMappers
from .....services.soap.nordea_corporate_access.nordea_ca_camt053_parser import (
    _parse_date_or_datetime,
    parse_camt053,
)

TEST_DATA_DIR = Path(__file__).resolve().parents[3] / "test_data"


def _load(filename):
    with open(os.path.join(TEST_DATA_DIR, filename), "rb") as f:
        return f.read()


class TestParseCamt053(BaseCase):

    def setUp(self):
        self.parsed = parse_camt053(_load("camt053extended_nca_sample.xml"))
        self.entries = self.parsed["transactions"]

    def test_rejects_wrong_message_type(self):
        with self.assertRaises(ValueError):
            parse_camt053(_load("pain001_wrong_root.xml"))

    def test_five_entries_parsed(self):
        self.assertEqual(len(self.entries), 5)

    def test_entry_amount_is_signed_by_indicator(self):
        entry = self.entries[0]
        self.assertEqual(entry["amount"], Decimal("-8.80"))
        self.assertEqual(entry["credit_debit"], "DBIT")

    def test_account_and_balances_parsed(self):
        self.assertEqual(
            self.parsed["account"]["currency"],
            "EUR",
        )
        self.assertEqual(
            self.parsed["balances"]["balance_start"],
            Decimal("500.50"),
        )
        self.assertEqual(
            self.parsed["balances"]["balance_end_real"],
            Decimal("491.49"),
        )

    def test_opening_balance_none_when_only_closing_present(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
                        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
                            <BkToCstmrStmt>
                                <Stmt>
                                    <Id>STMT001</Id>
                                    <Acct>
                                        <Id><IBAN>FI1234567890123456</IBAN></Id>
                                        <Ccy>EUR</Ccy>
                                    </Acct>
                                    <Bal>
                                        <Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>
                                        <Amt Ccy="EUR">491.49</Amt>
                                        <CdtDbtInd>CRDT</CdtDbtInd>
                                        <Dt><Dt>2026-09-01</Dt></Dt>
                                    </Bal>
                                </Stmt>
                            </BkToCstmrStmt>
                        </Document>"""
        parsed = parse_camt053(xml)
        self.assertIsNone(parsed["balances"]["opening"])
        self.assertIsNone(parsed["balances"]["balance_start"])
        self.assertEqual(parsed["balances"]["balance_end_real"], Decimal("491.49"))

    def test_closing_balance_none_when_only_opening_present(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
                    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
                        <BkToCstmrStmt>
                            <Stmt>
                                <Id>STMT001</Id>
                                <Acct>
                                    <Id><IBAN>FI1234567890123456</IBAN></Id>
                                    <Ccy>EUR</Ccy>
                                </Acct>
                                <Bal>
                                    <Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>
                                    <Amt Ccy="EUR">500.50</Amt>
                                    <CdtDbtInd>CRDT</CdtDbtInd>
                                    <Dt><Dt>2026-09-01</Dt></Dt>
                                </Bal>
                            </Stmt>
                        </BkToCstmrStmt>
                    </Document>"""
        parsed = parse_camt053(xml)
        self.assertIsNone(parsed["balances"]["closing"])
        self.assertIsNone(parsed["balances"]["balance_end_real"])
        self.assertEqual(parsed["balances"]["balance_start"], Decimal("500.50"))


class TestMapTransaction(BaseCase):

    def setUp(self):
        self.mapper = NordeaCAMappers()
        self.entries = parse_camt053(
            _load("camt053extended_nca_sample.xml")
        )["transactions"]

    def test_debit_amount_flipped_negative(self):
        dto = self.mapper._map_transaction(self.entries[0])
        self.assertEqual(dto.amount, Decimal("-8.80"))

    def test_credit_amount_stays_positive(self):
        dto = self.mapper._map_transaction(self.entries[1])
        self.assertEqual(dto.amount, Decimal("0.13"))

    def test_partner_name_uses_creditor_on_debit(self):
        dto = self.mapper._map_transaction(self.entries[0])
        self.assertEqual(dto.partner_name, "Creditor")

    def test_partner_name_uses_debtor_on_credit(self):
        dto = self.mapper._map_transaction(self.entries[1])
        self.assertEqual(dto.partner_name, "DEBTOR NAME")

    def test_only_first_tx_details_used_for_batched_entry(self):
        dto = self.mapper._map_transaction(self.entries[0])
        self.assertEqual(dto.partner_name, "Creditor")

    def test_transaction_id_from_acct_svcr_ref(self):
        dto = self.mapper._map_transaction(self.entries[0])
        self.assertEqual(dto.transaction_id, "2009222584LV000000")

    def test_payment_ref_from_first_structured_creditor_ref(self):
        dto = self.mapper._map_transaction(self.entries[0])
        self.assertEqual(dto.payment_ref, "RF332348236")

    def test_ref_from_unstructured_lines(self):
        dto = self.mapper._map_transaction(self.entries[2])
        self.assertIn("MESSAGE TO THE BENEFICIARY", dto.ref)

    def test_account_number_from_creditor_iban(self):
        dto = self.mapper._map_transaction(self.entries[0])
        self.assertEqual(dto.account_number, "FI7429501800000014")

    def test_raw_holds_full_entry(self):
        dto = self.mapper._map_transaction(self.entries[0])
        self.assertIn("bank_transaction_code", dto.raw)
        self.assertIn("details", dto.raw)

class TestParseCamtDateChoice(BaseCase):

    def _parse(self, choice_xml: str):
        xml = f"""<Ntry xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
            <BookgDt>{choice_xml}</BookgDt>
        </Ntry>"""
        parent = etree.fromstring(xml.encode())
        return _parse_date_or_datetime(parent, "BookgDt")

    def test_date_choice_returns_date(self):
        self.assertEqual(self._parse("<Dt>2026-01-02</Dt>"), date(2026, 1, 2))

    def test_utc_datetime_choice_returns_utc_date(self):
        self.assertEqual(
            self._parse("<DtTm>2026-01-02T00:30:00Z</DtTm>"),
            date(2026, 1, 2),
        )

    def test_offset_datetime_choice_returns_utc_date(self):
        # 00:30 at UTC+02:00 is 22:30 UTC on the previous day.
        self.assertEqual(
            self._parse("<DtTm>2026-01-02T00:30:00+02:00</DtTm>"),
            date(2026, 1, 1),
        )

    def test_naive_datetime_assumes_utc_and_warns(self):
        with self.assertLogs(level="WARNING") as captured:
            result = self._parse("<DtTm>2026-01-02T00:30:00</DtTm>")

        self.assertEqual(result, date(2026, 1, 2))
        self.assertTrue(any("assuming UTC" in message for message in captured.output))

    def test_missing_choice_returns_none(self):
        self.assertIsNone(self._parse(""))

    def test_invalid_date_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "Invalid CAMT.053 BookgDt/Dt"):
            self._parse("<Dt>not-a-date</Dt>")

    def test_invalid_datetime_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "Invalid CAMT.053 BookgDt/DtTm"):
            self._parse("<DtTm>not-a-datetime</DtTm>")