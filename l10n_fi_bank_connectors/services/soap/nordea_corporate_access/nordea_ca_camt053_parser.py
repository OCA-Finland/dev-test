from datetime import date
from functools import partial
from lxml import etree

from ....utils.formatting import normalize_iban, to_decimal
from ....utils.soap.nordea_ca_xml_utils import parse_iso_datetime, extract_text as _extract_text


# TODO move to constants
NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"
NSMAP = {"c": NS}

extract_text = partial(_extract_text, nsmap=NSMAP)

def _parse_date_or_datetime(parent, tag) -> date | None:
    block = parent.find(f"c:{tag}", namespaces=NSMAP)
    if block is None:
        return None

    date_text = extract_text(block, "c:Dt")
    datetime_text = extract_text(block, "c:DtTm")

    if date_text:
        try:
            return date.fromisoformat(date_text)
        except ValueError as exc:
            raise ValueError(f"Invalid CAMT.053 {tag}/Dt date: {date_text!r}") from exc

    if datetime_text:
        try:
            parsed = parse_iso_datetime(datetime_text)
        except ValueError as exc:
            raise ValueError(
                f"Invalid CAMT.053 {tag}/DtTm datetime: {datetime_text!r}"
            ) from exc

        return parsed.date()

    return None

def _parse_bktxcd(el):
    if el is None:
        return {}

    domain = extract_text(el, "c:Domn/c:Cd")
    family = extract_text(el, "c:Domn/c:Fmly/Cd")
    sub_family = extract_text(el, "c:Domn/c:Fmly/SubFmlyCd")
    proprietary = extract_text(el, "c:Prtry")

    return {
        "domain": domain,
        "family": family,
        "sub_family": sub_family,
        "proprietary": proprietary,
    }


def _parse_party(el):
    """Parse a party block (Dbtr/Cdtr/UltmtDbtr/UltmtCdtr) -> name + postal address."""
    if el is None:
        return {}

    party = {
        "name": extract_text(el, "c:Nm"),
        "street": extract_text(el, "c:PstlAdr/c:StrtNm"),
        "building_number": extract_text(el, "c:PstlAdr/c:BldgNb"),
        "postal_code": extract_text(el, "c:PstlAdr/c:PstCd"),
        "town": extract_text(el, "c:PstlAdr/c:TwnNm"),
        "country": extract_text(el, "c:PstlAdr/c:Ctry"),
    }

    account = el.find("c:Id", namespaces=NSMAP)
    if account is not None:
        party["iban"] = extract_text(account, "c:IBAN")
        party["other_account"] = extract_text(account, "c:Othr/c:Id")

    return {key: value for key, value in party.items() if value is not None}


def _parse_agent(el):
    """Parse a DbtrAgt/CdtrAgt block -> FinInstnId (BIC + country)."""
    if el is None:
        return {}

    institution = el.find("c:FinInstnId", namespaces=NSMAP)
    if institution is None:
        return {}

    return {
        "name": extract_text(institution, "c:Nm"),
        "bic": extract_text(institution, "c:BIC"),
        "bicfi": extract_text(institution, "c:BICFI"),
        "clearing_system_member_id": extract_text(
            institution,
            "c:ClrSysMmbId/c:MmbId",
        ),
    }


def _parse_amount_el(el):
    """Parse an Amt-shaped element (Ccy attribute + text amount)."""
    if el is None:
        return None

    value = (el.text or "").strip()
    if not value:
        return None

    return {
        "amount": to_decimal(value),
        "currency": el.get("Ccy"),
    }


def _parse_amt_dtls(el):
    """Parse AmtDtls block: InstdAmt, TxAmt (+ optional CcyXchg), PrtryAmt."""
    if el is None:
        return {}

    amounts = {}
    for key, path in (
        ("instructed", "c:InstdAmt"),
        ("transaction", "c:TxAmt/c:Amt"),
        ("counter_value", "c:CntrValAmt/c:Amt"),
        ("return", "c:RtrdInstdAmt"),
    ):
        amount = _parse_amount_el(el.find(path, namespaces=NSMAP))
        if amount:
            amounts[key] = amount

    return amounts


def _parse_rmt_inf(el):
    """Parse RmtInf block: repeatable Strd entries + repeatable Ustrd lines."""
    if el is None:
        return {}

    structured = []
    for item in el.findall("c:Strd", namespaces=NSMAP):
        structured.append({
            "reference": extract_text(item, "c:CdtrRefInf/c:Ref"),
            "reference_type": extract_text(item, "c:CdtrRefInf/c:Tp/c:CdOrPrtry/c:Cd"),
            "additional_info": [
                text.strip()
                for text in item.findall("c:AddtlRmtInf", namespaces=NSMAP)
                if text.text and text.text.strip()
            ],
        })

    unstructured = [
        text.text.strip()
        for text in el.findall("c:Ustrd", namespaces=NSMAP)
        if text.text and text.text.strip()
    ]

    return {
        "unstructured": unstructured,
        "structured": structured,
    }

def _parse_account(el):
    if el is None:
        return {}

    account_id = el.find("c:Id", namespaces=NSMAP)
    if account_id is None:
        return {}

    return {
        "iban": extract_text(account_id, "c:IBAN"),
        "other_account": extract_text(account_id, "c:Othr/c:Id"),
    }

def _parse_tx_dtls(el):
    """Parse a single TxDtls block."""
    if el is None:
        return {}

    refs = {
        "instruction_id": extract_text(el, "c:Refs/c:InstrId"),
        "end_to_end_id": extract_text(el, "c:Refs/c:EndToEndId"),
        "mandate_id": extract_text(el, "c:Refs/c:MndtId"),
        "account_servicer_reference": extract_text(el, "c:Refs/c:AcctSvcrRef"),
    }

    amount_details = _parse_amt_dtls(
        el.find("c:AmtDtls", namespaces=NSMAP)
    )

    related_parties = el.find("c:RltdPties", namespaces=NSMAP)

    return {
        **refs,
        "amount_details": amount_details,
        "booking_date": _parse_date_or_datetime(el, "BookgDt"),
        "value_date": _parse_date_or_datetime(el, "ValDt"),
        "debtor": _parse_party(el.find("c:RltdPties/c:Dbtr", namespaces=NSMAP)),
        "creditor": _parse_party(el.find("c:RltdPties/c:Cdtr", namespaces=NSMAP)),
        "debtor_agent": _parse_agent(
            el.find("c:RltdAgts/c:DbtrAgt", namespaces=NSMAP)
        ),
        "creditor_agent": _parse_agent(
            el.find("c:RltdAgts/c:CdtrAgt", namespaces=NSMAP)
        ),
        "debtor_account": _parse_account(
            related_parties.find("c:DbtrAcct", namespaces=NSMAP)
            if related_parties is not None else None
        ),
        "creditor_account": _parse_account(
            related_parties.find("c:CdtrAcct", namespaces=NSMAP)
            if related_parties is not None else None
        ),
        "remittance": _parse_rmt_inf(
            el.find("c:RmtInf", namespaces=NSMAP)
        ),
        "bank_transaction_code": _parse_bktxcd(
            el.find("c:BkTxCd", namespaces=NSMAP)
        ),
    }


def _parse_entry(ntry_el):
    """Parse a single Ntry block. TxDtls kept as a list even when there's only one."""
    amount_data = _parse_amount_el(
        ntry_el.find("c:Amt", namespaces=NSMAP)
    )
    if not amount_data:
        return None

    if extract_text(ntry_el, "c:CdtDbtInd") == "DBIT":
        amount_data["amount"] = -amount_data["amount"]

    tx_details = [
        _parse_tx_dtls(element)
        for element in ntry_el.findall(
            ".//c:TxDtls",
            namespaces=NSMAP,
        )
        if len(element)
    ]

    entry = {
        "transaction_id": (
            extract_text(ntry_el, "c:AcctSvcrRef")
            or extract_text(ntry_el, "c:NtryRef")
        ),
        "entry_reference": extract_text(ntry_el, "c:NtryRef"),
        "amount": amount_data["amount"],
        "currency": amount_data["currency"],
        "credit_debit": extract_text(ntry_el, "c:CdtDbtInd"),
        "status": extract_text(ntry_el, "c:Sts"),
        "booking_date": _parse_date_or_datetime(ntry_el, "BookgDt"),
        "value_date": _parse_date_or_datetime(ntry_el, "ValDt"),
        "account_servicer_reference": extract_text(ntry_el, "c:AcctSvcrRef"),
        "bank_transaction_code": _parse_bktxcd(
            ntry_el.find("c:BkTxCd", namespaces=NSMAP)
        ),
        "details": tx_details,
        "raw": etree.tostring(ntry_el, encoding="unicode"),
    }

    return entry


def _parse_balance(bal_el):
    amount = _parse_amount_el(
        bal_el.find("c:Amt", namespaces=NSMAP)
    )
    if not amount:
        return None

    if extract_text(bal_el, "c:CdtDbtInd") == "DBIT":
        amount["amount"] = -amount["amount"]

    return {
        "type": (
            extract_text(bal_el, "c:Tp/c:CdOrPrtry/c:Cd")
            or extract_text(bal_el, "c:Tp/c:CdOrPrtry/c:Prtry")
        ),
        "amount": amount["amount"],
        "currency": amount["currency"],
        "date": _parse_date_or_datetime(bal_el, "Dt"),
    }


def parse_camt053(xml_content: bytes) -> dict:
    """Parse a camt.053.001.02 Extended statement into a nested dict."""
    root = etree.fromstring(xml_content)

    statement = root.find(".//c:Stmt", namespaces=NSMAP)
    if statement is None:
        raise ValueError("CAMT.053 response does not contain a statement")

    account = statement.find("c:Acct", namespaces=NSMAP)
    account_id = account.find("c:Id", namespaces=NSMAP)

    balances = [
        balance
        for balance in (
            _parse_balance(element)
            for element in statement.findall("c:Bal", namespaces=NSMAP)
        )
        if balance
    ]

    entries = [
        entry
        for entry in (
            _parse_entry(element)
            for element in statement.findall("c:Ntry", namespaces=NSMAP)
        )
        if entry
    ]

    opening = next(
        (item for item in balances if item["type"] == "OPBD"),
        None,
    )
    closing = next(
        (item for item in balances if item["type"] == "CLBD"),
        None,
    )

    iban = extract_text(account_id, "c:IBAN")

    return {
        "statement_id": extract_text(statement, "c:Id"),
        "account": {
            "iban": normalize_iban(iban) if iban else None,
            "currency": extract_text(account, "c:Ccy"),
            "name": extract_text(account, "c:Ownr/c:Nm"),
            "bic": extract_text(account, "c:Svcr/c:FinInstnId/c:BIC"),
        },
        "balances": {
            "opening": opening,
            "closing": closing,
            "balance_start": opening["amount"] if opening else None,
            "balance_end_real": closing["amount"] if closing else None,
        },
        "transactions": entries,
    }