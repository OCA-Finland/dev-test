from datetime import date, datetime, timezone
from lxml import etree

from .constants.pain001 import (
    PAIN001_NAMESPACE, TAG_DOCUMENT, TAG_CSTMR_CDT_TRF_INITN, TAG_GRP_HDR, TAG_MSG_ID,
    TAG_CRE_DT_TM, TAG_NB_OF_TXS, TAG_INITG_PTY, TAG_NM, TAG_PMT_INF,
    TAG_PMT_INF_ID, TAG_PMT_MTD, TAG_BTCH_BOOKG, TAG_CTRL_SUM, TAG_REQD_EXCTN_DT,
    TAG_DBTR, TAG_DBTR_ACCT, TAG_DBTR_AGT, TAG_FIN_INSTN_ID, TAG_OTHR, TAG_ID,
    TAG_IBAN, TAG_CDT_TRF_TX_INF, TAG_PMT_ID, TAG_INSTR_ID, TAG_END_TO_END_ID,
    TAG_AMT, TAG_INSTD_AMT, TAG_CDTR_AGT, TAG_CDTR, TAG_CDTR_ACCT, TAG_RMT_INF,
    TAG_USTRD, TAG_STRD, TAG_CDTR_REF_INF, TAG_TP, TAG_CD_OR_PRTRY, TAG_CD,
    TAG_REF, PMT_MTD_TRANSFER, CREDITOR_REFERENCE_TYPE_SCOR, NOTPROVIDED_BIC,
)
from .nordea_ca_dtos import NordeaCAPaymentRequestDTO
from ....utils.clock import utc_now, utc_today
from ....utils.formatting import normalize_iban


def build_pain001_payload(payment: NordeaCAPaymentRequestDTO) -> bytes:
    """
    Build a pain.001.001.09 Customer Credit Transfer Initiation payload for a
    single payment, wrapped in one mandatory batch (PmtInf) block per NCA's
    Corporate Access Payables requirements.
    """
    document = etree.Element(f"{{{PAIN001_NAMESPACE}}}{TAG_DOCUMENT}", nsmap={None: PAIN001_NAMESPACE})
    cstmr = etree.SubElement(document, f"{{{PAIN001_NAMESPACE}}}{TAG_CSTMR_CDT_TRF_INITN}")

    # MsgId, PmtInfId, EndToEndId and InstrId all carry the payment's single ID
    # (banking_payment_id, see HT00238).
    # Nordea requires MsgId, PmtInfId and EndToEndId to be unique within 90 calendar
    # days, uses each for duplicate control, and returns them in pain.002
    # (OrgnlMsgId / OrgnlPmtInfId / OrgnlEndToEndId).
    # !if several payments are ever batched into one file, MsgId and PmtInfId need their separate ids.
    grp_hdr = etree.SubElement(cstmr, f"{{{PAIN001_NAMESPACE}}}{TAG_GRP_HDR}")
    _add(grp_hdr, TAG_MSG_ID, payment.end_to_end_id)
    _add(grp_hdr, TAG_CRE_DT_TM, utc_now().isoformat())
    _add(grp_hdr, TAG_NB_OF_TXS, "1")
    initg_pty = etree.SubElement(grp_hdr, f"{{{PAIN001_NAMESPACE}}}{TAG_INITG_PTY}")
    _add(initg_pty, TAG_NM, payment.debtor_name)

    pmt_inf = etree.SubElement(cstmr, f"{{{PAIN001_NAMESPACE}}}{TAG_PMT_INF}")
    _add(pmt_inf, TAG_PMT_INF_ID, payment.end_to_end_id)
    _add(pmt_inf, TAG_PMT_MTD, PMT_MTD_TRANSFER)
    _add(pmt_inf, TAG_BTCH_BOOKG, "true")
    _add(pmt_inf, TAG_NB_OF_TXS, "1")
    _add(pmt_inf, TAG_CTRL_SUM, f"{payment.amount:.2f}")
    exec_date = payment.request_execution_date or utc_today()
    _add(pmt_inf, TAG_REQD_EXCTN_DT, exec_date.isoformat())

    dbtr = etree.SubElement(pmt_inf, f"{{{PAIN001_NAMESPACE}}}{TAG_DBTR}")
    _add(dbtr, TAG_NM, payment.debtor_name)

    dbtr_acct = etree.SubElement(pmt_inf, f"{{{PAIN001_NAMESPACE}}}{TAG_DBTR_ACCT}")
    dbtr_acct_id = etree.SubElement(dbtr_acct, f"{{{PAIN001_NAMESPACE}}}{TAG_ID}")
    _add(dbtr_acct_id, TAG_IBAN, normalize_iban(payment.debtor_iban))

    _add_notprovided_agent(pmt_inf, TAG_DBTR_AGT)

    tx = etree.SubElement(pmt_inf, f"{{{PAIN001_NAMESPACE}}}{TAG_CDT_TRF_TX_INF}")
    pmt_id = etree.SubElement(tx, f"{{{PAIN001_NAMESPACE}}}{TAG_PMT_ID}")
    # InstrId reuses EndToEndId too — not unique/dedup-relevant per spec, so
    # collision with EndToEndId's own uniqueness requirement is not a concern.
    _add(pmt_id, TAG_INSTR_ID, payment.end_to_end_id)
    _add(pmt_id, TAG_END_TO_END_ID, payment.end_to_end_id)

    amt = etree.SubElement(tx, f"{{{PAIN001_NAMESPACE}}}{TAG_AMT}")
    instd_amt = etree.SubElement(amt, f"{{{PAIN001_NAMESPACE}}}{TAG_INSTD_AMT}")
    instd_amt.set("Ccy", payment.currency)
    instd_amt.text = f"{payment.amount:.2f}"

    _add_notprovided_agent(tx, TAG_CDTR_AGT)

    cdtr = etree.SubElement(tx, f"{{{PAIN001_NAMESPACE}}}{TAG_CDTR}")
    _add(cdtr, TAG_NM, payment.creditor_name)

    cdtr_acct = etree.SubElement(tx, f"{{{PAIN001_NAMESPACE}}}{TAG_CDTR_ACCT}")
    cdtr_acct_id = etree.SubElement(cdtr_acct, f"{{{PAIN001_NAMESPACE}}}{TAG_ID}")
    _add(cdtr_acct_id, TAG_IBAN, normalize_iban(payment.creditor_iban))

    _add_remittance_info(tx, payment)

    return etree.tostring(document, xml_declaration=True, encoding="UTF-8")


def _add(parent, tag: str, value) -> None:
    if value is None:
        return
    el = etree.SubElement(parent, f"{{{PAIN001_NAMESPACE}}}{tag}")
    el.text = str(value)


def _add_notprovided_agent(parent, agent_tag: str) -> None:
    agent = etree.SubElement(parent, f"{{{PAIN001_NAMESPACE}}}{agent_tag}")
    fin_instn_id = etree.SubElement(agent, f"{{{PAIN001_NAMESPACE}}}{TAG_FIN_INSTN_ID}")
    othr = etree.SubElement(fin_instn_id, f"{{{PAIN001_NAMESPACE}}}{TAG_OTHR}")
    _add(othr, TAG_ID, NOTPROVIDED_BIC)


def _add_remittance_info(tx, payment: NordeaCAPaymentRequestDTO) -> None:
    rmt_inf = etree.SubElement(tx, f"{{{PAIN001_NAMESPACE}}}{TAG_RMT_INF}")
    reference = (payment.reference or "").strip()
    if reference:
        strd = etree.SubElement(rmt_inf, f"{{{PAIN001_NAMESPACE}}}{TAG_STRD}")
        cdtr_ref_inf = etree.SubElement(strd, f"{{{PAIN001_NAMESPACE}}}{TAG_CDTR_REF_INF}")
        tp = etree.SubElement(cdtr_ref_inf, f"{{{PAIN001_NAMESPACE}}}{TAG_TP}")
        cd_or_prtry = etree.SubElement(tp, f"{{{PAIN001_NAMESPACE}}}{TAG_CD_OR_PRTRY}")
        _add(cd_or_prtry, TAG_CD, CREDITOR_REFERENCE_TYPE_SCOR)
        _add(cdtr_ref_inf, TAG_REF, reference)
    elif payment.message:
        _add(rmt_inf, TAG_USTRD, payment.message)