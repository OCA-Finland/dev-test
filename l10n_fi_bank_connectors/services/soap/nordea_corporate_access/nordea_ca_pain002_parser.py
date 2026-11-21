from lxml import etree

from ....utils.soap.nordea_ca_xml_utils import extract_text, parse_datetime
from .constants.pain002 import (
    PAIN002_NAMESPACE,
    ORIGINAL_MSG_NAME_CAMT_055,
    TAG_ADDTL_INF,
    TAG_CD,
    TAG_CRE_DT_TM,
    TAG_CSTMR_PMT_STS_RPT,
    TAG_GRP_HDR,
    TAG_GRP_STS,
    TAG_MSG_ID,
    TAG_ORGNL_END_TO_END_ID,
    TAG_ORGNL_GRP_INF_AND_STS,
    TAG_ORGNL_INSTR_ID,
    TAG_ORGNL_MSG_ID,
    TAG_ORGNL_MSG_NM_ID,
    TAG_ORGNL_PMT_INF_AND_STS,
    TAG_ORGNL_PMT_INF_ID,
    TAG_PMT_INF_STS,
    TAG_RSN,
    TAG_STS_RSN_INF,
    TAG_TX_INF_AND_STS,
    TAG_TX_STS,
)
from .nordea_ca_dtos import (
    PaymentStatusDTO,
    PaymentStatusReportDTO,
    StatusReasonDTO,
    TransactionStatusDTO,
)
from .nordea_ca_dtos import PaymentStatusReportDTO, StatusReasonDTO



NS_PREFIX = "p"


def _path(*tags: str) -> str:
    """Build a prefixed child path, e.g. _path("Rsn", "Cd") -> 'p:Rsn/p:Cd'."""
    return "/".join(f"{NS_PREFIX}:{tag}" for tag in tags)

def _parse_transaction_status(el, nsmap) -> TransactionStatusDTO:
    """Parse one <TxInfAndSts> entry (transaction level)."""
    return TransactionStatusDTO(
        end_to_end_id=extract_text(el, _path(TAG_ORGNL_END_TO_END_ID), nsmap),
        instruction_id=extract_text(el, _path(TAG_ORGNL_INSTR_ID), nsmap),
        status=extract_text(el, _path(TAG_TX_STS), nsmap),
        reasons=_parse_status_reasons(el, nsmap),
    )

def _parse_payment_status(el, nsmap) -> PaymentStatusDTO:
    """Parse one <OrgnlPmtInfAndSts> entry (payment level) with its transactions."""
    return PaymentStatusDTO(
        payment_info_id=extract_text(el, _path(TAG_ORGNL_PMT_INF_ID), nsmap),
        status=extract_text(el, _path(TAG_PMT_INF_STS), nsmap),
        reasons=_parse_status_reasons(el, nsmap),
        transactions=[
            _parse_transaction_status(transaction, nsmap)
            for transaction in el.findall(_path(TAG_TX_INF_AND_STS), nsmap)
        ],
    )

def _parse_status_reasons(parent, nsmap) -> list[StatusReasonDTO]:
    """Parse every direct <StsRsnInf> child of parent (reason code + repeatable <AddtlInf>)."""
    return [
        StatusReasonDTO(
            code=extract_text(reason, _path(TAG_RSN, TAG_CD), nsmap),
            additional_info=[
                text.text.strip()
                for text in reason.findall(_path(TAG_ADDTL_INF), nsmap)
                if text.text and text.text.strip()
            ],
        )
        for reason in parent.findall(_path(TAG_STS_RSN_INF), nsmap)
    ]


def parse_pain002(xml_content: bytes) -> PaymentStatusReportDTO:
    """Parse a pain.002.001.10 status report (group, payment and transaction levels).

    Raises ValueError when the content is not a supported pain.002 report.
    """
    try:
        root = etree.fromstring(xml_content)
    except etree.XMLSyntaxError as exc:
        raise ValueError("pain.002 file is not well-formed XML") from exc

    # Only pain.002.001.10 is supported
    namespace = etree.QName(root).namespace
    if namespace != PAIN002_NAMESPACE:
        raise ValueError(
            f"unsupported pain.002 namespace {namespace!r}, expected {PAIN002_NAMESPACE!r}"
        )
    nsmap = {NS_PREFIX: namespace}

    if root.find(f".//{_path(TAG_CSTMR_PMT_STS_RPT)}", nsmap) is None:
        raise ValueError("pain.002 file does not contain a CstmrPmtStsRpt element")

    report = PaymentStatusReportDTO()

    group_header = root.find(f".//{_path(TAG_GRP_HDR)}", nsmap)
    if group_header is not None:
        report.message_id = extract_text(group_header, _path(TAG_MSG_ID), nsmap)
        report.created_at = parse_datetime(group_header, _path(TAG_CRE_DT_TM), nsmap)

    group_info = root.find(f".//{_path(TAG_ORGNL_GRP_INF_AND_STS)}", nsmap)
    if group_info is not None:
        report.original_message_id = extract_text(group_info, _path(TAG_ORGNL_MSG_ID), nsmap)
        report.original_message_name = extract_text(group_info, _path(TAG_ORGNL_MSG_NM_ID), nsmap)
        report.group_status = extract_text(group_info, _path(TAG_GRP_STS), nsmap)
        report.reasons = _parse_status_reasons(group_info, nsmap)

    report.payments = [
        _parse_payment_status(payment, nsmap)
        for payment in root.findall(f".//{_path(TAG_ORGNL_PMT_INF_AND_STS)}", nsmap)
    ]

    return report

# camt.055 (CustomerPaymentCancellationRequest) -- NOT IMPLEMENTED.
#
# camt.055 is a request we would send to Nordea (file type NDCAPCANXMLI, Secure
# Envelope spec Appendix B) to cancel a payment that was already submitted. We do
# not send any yet.
#
# Nordea answers such a request with a pain.002 whose OrgnlMsgNmId is
# "camt.055.001.08". That report only covers the group level: GrpSts is ACTC
# (technical validation passed) or RJCT (the whole request was rejected, with the
# reason in StsRsnInf/AddtlInf). The payment and transaction levels are not used
# for camt.055 (Nordea MIG pain.002.001.10, pp. 12-13).
#
# Such a report says nothing about the state of the original payment, so it must
# never go through status mapping: the ingestion loop has to skip it. The outcome
# of the cancellation itself arrives as a separate camt.029 file (NDCAPCANXMLO,
# "Resolution of Investigation"). ASSUMPTION: inferred from the Appendix B file
# names, not verified against a camt.029 MIG.
#
# Skipping is defensive: we send no cancellations today, so these replies are not
# expected.
def is_cancellation_reply(report: PaymentStatusReportDTO) -> bool:
    """True when the report answers a camt.055 cancellation request.

    OrgnlMsgNmId is required by the MIG (p. 12). If it is missing, the file does
    not conform to the spec; it is then NOT treated as a cancellation reply and is
    processed as usual, so correlation finds no match and the unmatched IDs get
    logged by the ingestion loop.
    """
    return report.original_message_name == ORIGINAL_MSG_NAME_CAMT_055