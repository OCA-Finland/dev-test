import base64

from ...services.soap.nordea_corporate_access.constants.namespaces import NS_SOAPENV
from ...services.soap.nordea_corporate_access.constants.nordea_ws import FILE_TYPE_CAMT_053_EXTENDED
from ...services.soap.nordea_corporate_access.constants.pain002 import PAIN002_NAMESPACE


def _minimal_camt053_xml(iban, currency="EUR", balances=None, entries=None):
    """balances: list of (type_code, amount, date_str) tuples.
    entries: list of (amount, credit_debit_ind) tuples, e.g. ("100.00", "DBIT")."""
    bal_xml = ""
    for type_code, amount, date_str in (balances or []):
        bal_xml += f"""
            <Bal>
                <Tp><CdOrPrtry><Cd>{type_code}</Cd></CdOrPrtry></Tp>
                <Amt Ccy="{currency}">{amount}</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <Dt><Dt>{date_str}</Dt></Dt>
            </Bal>"""

    ntry_xml = ""
    for i, (amount, cdt_dbt_ind) in enumerate(entries or [], start=1):
        ntry_xml += f"""
            <Ntry>
                <NtryRef>{i}</NtryRef>
                <Amt Ccy="{currency}">{amount}</Amt>
                <CdtDbtInd>{cdt_dbt_ind}</CdtDbtInd>
                <Sts>BOOK</Sts>
            </Ntry>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
                    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
                        <BkToCstmrStmt>
                            <Stmt>
                                <Id>STMT001</Id>
                                <Acct>
                                    <Id><IBAN>{iban}</IBAN></Id>
                                    <Ccy>{currency}</Ccy>
                                </Acct>{bal_xml}{ntry_xml}
                            </Stmt>
                        </BkToCstmrStmt>
                    </Document>""".encode()

def _minimal_pain002_xml(
    message_id="MSG001",
    created_at="2026-09-09T10:30:00Z",
    original_message_id="ORIG001",
    original_message_name="pain.001.001.09",
    group_status="ACTC",
    group_reasons=None,
    namespace=PAIN002_NAMESPACE,
):
    """Group-level pain.002 report.
    group_reasons: list of (reason_code, [additional_info, ...]) tuples.
    namespace: None omits the xmlns attribute entirely."""
    xmlns = f' xmlns="{namespace}"' if namespace else ""
    grp_sts_xml = f"<GrpSts>{group_status}</GrpSts>" if group_status else ""

    reasons_xml = ""
    for code, additional_info in (group_reasons or []):
        addtl_xml = "".join(f"<AddtlInf>{text}</AddtlInf>" for text in additional_info)
        reasons_xml += f"<StsRsnInf><Rsn><Cd>{code}</Cd></Rsn>{addtl_xml}</StsRsnInf>"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
                    <Document{xmlns}>
                        <CstmrPmtStsRpt>
                            <GrpHdr>
                                <MsgId>{message_id}</MsgId>
                                <CreDtTm>{created_at}</CreDtTm>
                            </GrpHdr>
                            <OrgnlGrpInfAndSts>
                                <OrgnlMsgId>{original_message_id}</OrgnlMsgId>
                                <OrgnlMsgNmId>{original_message_name}</OrgnlMsgNmId>
                                {grp_sts_xml}{reasons_xml}
                            </OrgnlGrpInfAndSts>
                        </CstmrPmtStsRpt>
                    </Document>""".encode()

def _wrap_wire_response(inner_xml):
    """Wrap an inline ApplicationResponse XML string in the SOAP wire format.

    The wire ApplicationResponse element carries the real (inner) response
    as base64-encoded text, which is what parse_application_response expects.
    """
    encoded = base64.b64encode(inner_xml.strip().encode()).decode()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
        <s:Envelope xmlns:s="{NS_SOAPENV}">
            <s:Body>
                <ApplicationResponse xmlns="http://model.bxd.fi">{encoded}</ApplicationResponse>
            </s:Body>
        </s:Envelope>""".encode()


def _file_content_response(content_bytes, compressed=False, compression_method=None):
    """content_bytes: the (optionally already-compressed) payload to base64-encode."""
    encoded = base64.b64encode(content_bytes).decode()
    compressed_xml = "true" if compressed else "false"
    method_xml = (
        f"<CompressionMethod>{compression_method}</CompressionMethod>"
        if compression_method else ""
    )
    return _wrap_wire_response(f"""
            <ApplicationResponse xmlns="http://bxd.fi/xmldata/">
                <CustomerId>12345678</CustomerId>
                <Timestamp>2026-09-09T10:35:00Z</Timestamp>
                <ResponseCode>0</ResponseCode>
                <Compressed>{compressed_xml}</Compressed>
                {method_xml}
                <Content>{encoded}</Content>
            </ApplicationResponse>""")


def _file_list_response(file_descriptors):
    """file_descriptors: list of (file_reference, target_id) tuples."""
    fds = ""
    for ref, target in file_descriptors:
            fds += f"""
            <FileDescriptor>
                <FileReference>{ref}</FileReference>
                <TargetId>{target}</TargetId>
                <FileType>{FILE_TYPE_CAMT_053_EXTENDED}</FileType>
                <Status>AVAILABLE</Status>
                <ServiceId>NDAREXXMLO</ServiceId>
            </FileDescriptor>"""
    return _wrap_wire_response(f"""
        <ApplicationResponse xmlns="http://bxd.fi/xmldata/">
            <CustomerId>12345678</CustomerId>
            <Timestamp>2026-09-09T10:30:00Z</Timestamp>
            <ResponseCode>0</ResponseCode>
            <FileDescriptors>{fds}
            </FileDescriptors>
        </ApplicationResponse>""")


def _error_response(response_code, response_text):
    return _wrap_wire_response(f"""
        <ApplicationResponse xmlns="http://bxd.fi/xmldata/">
            <CustomerId>12345678</CustomerId>
            <Timestamp>2026-09-09T10:30:00Z</Timestamp>
            <ResponseCode>{response_code}</ResponseCode>
            <ResponseText>{response_text}</ResponseText>
        </ApplicationResponse>""")

def _pain002_optional(tag, value):
    return f"<{tag}>{value}</{tag}>" if value else ""


def _pain002_reasons_xml(reasons):
    """reasons: list of (reason_code, [additional_info, ...]) tuples."""
    xml = ""
    for code, additional_info in (reasons or []):
        addtl_xml = "".join(f"<AddtlInf>{text}</AddtlInf>" for text in additional_info)
        xml += f"<StsRsnInf><Rsn><Cd>{code}</Cd></Rsn>{addtl_xml}</StsRsnInf>"
    return xml


def _pain002_transaction_xml(transaction):
    return (
        "<TxInfAndSts>"
        + _pain002_optional("OrgnlInstrId", transaction.get("instruction_id"))
        + _pain002_optional("OrgnlEndToEndId", transaction.get("end_to_end_id"))
        + _pain002_optional("TxSts", transaction.get("status"))
        + _pain002_reasons_xml(transaction.get("reasons"))
        + "</TxInfAndSts>"
    )


def _pain002_payment_xml(payment):
    return (
        "<OrgnlPmtInfAndSts>"
        + _pain002_optional("OrgnlPmtInfId", payment.get("payment_info_id"))
        + _pain002_optional("PmtInfSts", payment.get("status"))
        + _pain002_reasons_xml(payment.get("reasons"))
        + "".join(
            _pain002_transaction_xml(transaction)
            for transaction in payment.get("transactions", [])
        )
        + "</OrgnlPmtInfAndSts>"
    )


def _minimal_pain002_xml(
    message_id="MSG001",
    created_at="2026-09-09T10:30:00Z",
    original_message_id="ORIG001",
    original_message_name="pain.001.001.09",
    group_status="ACTC",
    group_reasons=None,
    payments=None,
    namespace=PAIN002_NAMESPACE,
):
    """pain.002 report.
    group_reasons: list of (reason_code, [additional_info, ...]) tuples.
    payments: list of dicts with optional keys payment_info_id, status, reasons,
        transactions. Each transaction is a dict with optional keys
        end_to_end_id, instruction_id, status, reasons.
    namespace: None omits the xmlns attribute entirely."""
    xmlns = f' xmlns="{namespace}"' if namespace else ""
    grp_sts_xml = _pain002_optional("GrpSts", group_status)
    group_reasons_xml = _pain002_reasons_xml(group_reasons)
    payments_xml = "".join(_pain002_payment_xml(payment) for payment in (payments or []))

    return f"""<?xml version="1.0" encoding="UTF-8"?>
                    <Document{xmlns}>
                        <CstmrPmtStsRpt>
                            <GrpHdr>
                                <MsgId>{message_id}</MsgId>
                                <CreDtTm>{created_at}</CreDtTm>
                            </GrpHdr>
                            <OrgnlGrpInfAndSts>
                                <OrgnlMsgId>{original_message_id}</OrgnlMsgId>
                                <OrgnlMsgNmId>{original_message_name}</OrgnlMsgNmId>
                                {grp_sts_xml}{group_reasons_xml}
                            </OrgnlGrpInfAndSts>{payments_xml}
                        </CstmrPmtStsRpt>
                    </Document>""".encode()