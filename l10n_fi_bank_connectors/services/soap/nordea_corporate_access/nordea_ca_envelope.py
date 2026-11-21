import base64
from lxml import etree

from .constants.namespaces import NS_SOAPENV, NS_MODEL, NS_SERVICE, NS_PREFIX_SOAPENV, NS_PREFIX_MODEL
from .constants.soap_envelope import (
    TAG_ENVELOPE, TAG_BODY, TAG_UPLOAD_FILE_IN, TAG_REQUEST_HEADER,
    TAG_APPLICATION_REQUEST, TAG_SENDER_ID, TAG_REQUEST_ID, TAG_TIMESTAMP,
    TAG_LANGUAGE, TAG_USER_AGENT, TAG_RECEIVER_ID,
)
from .nordea_ca_dtos import RequestHeaderDTO



def build_envelope(
    body_tag: str,
    header: RequestHeaderDTO,
    signed_application_request: etree._Element,
) -> etree._Element:
    """
    Build the SOAP envelope for one CorporateFileService operation, per the
    WSDL's document/literal request structure. All operations share the same
    layout (RequestHeader + base64 ApplicationRequest); only the body element
    name differs (uploadFilein, downloadFileListin, downloadFilein, ...).
    """
    envelope = etree.Element("{%s}%s" % (NS_SOAPENV, TAG_ENVELOPE), nsmap={NS_PREFIX_SOAPENV: NS_SOAPENV})
    body = etree.SubElement(envelope, "{%s}%s" % (NS_SOAPENV, TAG_BODY))
    request_el = etree.SubElement(
        body, "{%s}%s" % (NS_SERVICE, body_tag), nsmap={NS_PREFIX_MODEL: NS_MODEL}
    )

    header_el = etree.SubElement(request_el, "{%s}%s" % (NS_MODEL, TAG_REQUEST_HEADER))
    etree.SubElement(header_el, "{%s}%s" % (NS_MODEL, TAG_SENDER_ID)).text = header.sender_id
    etree.SubElement(header_el, "{%s}%s" % (NS_MODEL, TAG_REQUEST_ID)).text = header.request_id
    etree.SubElement(header_el, "{%s}%s" % (NS_MODEL, TAG_TIMESTAMP)).text = header.timestamp.isoformat()
    if header.language is not None:
        etree.SubElement(header_el, "{%s}%s" % (NS_MODEL, TAG_LANGUAGE)).text = header.language
    if header.user_agent is not None:
        etree.SubElement(header_el, "{%s}%s" % (NS_MODEL, TAG_USER_AGENT)).text = header.user_agent
    etree.SubElement(header_el, "{%s}%s" % (NS_MODEL, TAG_RECEIVER_ID)).text = header.receiver_id

    app_request_bytes = etree.tostring(signed_application_request)
    app_request_el = etree.SubElement(request_el, "{%s}%s" % (NS_SERVICE, TAG_APPLICATION_REQUEST))
    app_request_el.text = base64.b64encode(app_request_bytes).decode()

    return envelope

def build_upload_file_envelope(
    header: RequestHeaderDTO,
    signed_application_request: etree._Element,
) -> etree._Element:
    """Build the SOAP envelope for uploadFile (thin wrapper over build_envelope)."""
    return build_envelope(TAG_UPLOAD_FILE_IN, header, signed_application_request)