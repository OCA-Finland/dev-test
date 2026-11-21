"""Tag names and constants for the pain.002.001.10 Customer Payment Status Report."""

PAIN002_NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.10"

# Root and group header
TAG_DOCUMENT = "Document"
TAG_CSTMR_PMT_STS_RPT = "CstmrPmtStsRpt"
TAG_GRP_HDR = "GrpHdr"
TAG_MSG_ID = "MsgId"
TAG_CRE_DT_TM = "CreDtTm"

# Original group information and status (group level)
TAG_ORGNL_GRP_INF_AND_STS = "OrgnlGrpInfAndSts"
TAG_ORGNL_MSG_ID = "OrgnlMsgId"
TAG_ORGNL_MSG_NM_ID = "OrgnlMsgNmId"
TAG_GRP_STS = "GrpSts"

# Original payment information and status (payment level)
TAG_ORGNL_PMT_INF_AND_STS = "OrgnlPmtInfAndSts"
TAG_ORGNL_PMT_INF_ID = "OrgnlPmtInfId"
TAG_PMT_INF_STS = "PmtInfSts"

# Transaction information and status (transaction level)
TAG_TX_INF_AND_STS = "TxInfAndSts"
TAG_ORGNL_INSTR_ID = "OrgnlInstrId"
TAG_ORGNL_END_TO_END_ID = "OrgnlEndToEndId"
TAG_ORGNL_UETR = "OrgnlUETR"
TAG_TX_STS = "TxSts"

# Status reason (repeatable at every level)
TAG_STS_RSN_INF = "StsRsnInf"
TAG_RSN = "Rsn"
TAG_CD = "Cd"
TAG_ADDTL_INF = "AddtlInf"

# Original transaction reference (only for ACWC/MS02 and rejected Strd references)
TAG_ORGNL_TX_REF = "OrgnlTxRef"
TAG_CDTR_ACCT = "CdtrAcct"
TAG_ID = "Id"
TAG_IBAN = "IBAN"

# OrgnlMsgNmId values: which message this report refers to
ORIGINAL_MSG_NAME_PAIN_001 = "pain.001.001.09"
ORIGINAL_MSG_NAME_CAMT_055 = "camt.055.001.08"

# Group level statuses (GrpSts)
GROUP_STATUS_ACTC = "ACTC"
GROUP_STATUS_RJCT = "RJCT"

# Payment level statuses (PmtInfSts)
PAYMENT_STATUS_ACCP = "ACCP"
PAYMENT_STATUS_ACSP = "ACSP"  # reserved by Nordea for future use
PAYMENT_STATUS_ACWC = "ACWC"
PAYMENT_STATUS_PART = "PART"
PAYMENT_STATUS_PDNG = "PDNG"
PAYMENT_STATUS_RJCT = "RJCT"


# ACSC (settlement completed) is an ISO code that Nordea does NOT list in MIG 7.1.3.
# It is kept as a single level-independent constant and mapped defensively.
STATUS_ACSC = "ACSC"

# Transaction level statuses (TxSts); PART is not used at this level
TRANSACTION_STATUS_ACCP = "ACCP"
TRANSACTION_STATUS_ACSP = "ACSP"  # reserved by Nordea for future use
TRANSACTION_STATUS_ACWC = "ACWC"
TRANSACTION_STATUS_PDNG = "PDNG"
TRANSACTION_STATUS_RJCT = "RJCT"

# Status reason codes (StsRsnInf/Rsn/Cd)
REASON_NARR = "NARR"  # Nordea free text, carried in AddtlInf
REASON_MS02 = "MS02"  # with ACWC: creditor account changed (Finland only)
REASON_DU01 = "DU01"
REASON_AM11 = "AM11"
REASON_AM04 = "AM04"
REASON_AM09 = "AM09"
REASON_DT05 = "DT05"
REASON_DT06 = "DT06"
REASON_BE04 = "BE04"
REASON_RR07 = "RR07"
REASON_AC03 = "AC03"
REASON_RC10 = "RC10"
REASON_RC07 = "RC07"