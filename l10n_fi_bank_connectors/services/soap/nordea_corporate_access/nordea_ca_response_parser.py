import base64
import binascii

from lxml import etree
from typing import Optional

from ...error_handling.soap_error_types import BankingProtocolError
from .constants.namespaces import NS_SOAPENV, XMLDATA_NAMESPACE
from .constants.soap_envelope import TAG_BODY, TAG_ENVELOPE
from .nordea_ca_dtos import ApplicationResponseDTO
from ....utils.soap.nordea_ca_xml_utils import (
    extract_text, 
    parse_datetime, 
    parse_bool, 
    parse_float, 
    parse_int
    )


def parse_application_response(response_element: etree._Element) -> ApplicationResponseDTO:
    """
    Parse a SOAP <ApplicationResponse> element into ApplicationResponseDTO.
    
    The response may be wrapped in a SOAP envelope; we extract the ApplicationResponse
    from within the SOAP body.
    """
    # If the element is a SOAP Envelope, extract the body and then the ApplicationResponse
    app_response_el = _extract_application_response_element(response_element)
    
    if app_response_el is None:
        raise ValueError("No ApplicationResponse element found in response")
    
    nsmap = {"bxd": XMLDATA_NAMESPACE}
    
    return ApplicationResponseDTO(
        customer_id=extract_text(app_response_el, "bxd:CustomerId", nsmap),
        timestamp=parse_datetime(app_response_el, "bxd:Timestamp", nsmap),
        response_code=extract_text(app_response_el, "bxd:ResponseCode", nsmap),
        response_text=extract_text(app_response_el, "bxd:ResponseText", nsmap),
        execution_serial=extract_text(app_response_el, "bxd:ExecutionSerial", nsmap),
        encrypted=parse_bool(app_response_el, "bxd:Encrypted", nsmap),
        encryption_method=extract_text(app_response_el, "bxd:EncryptionMethod", nsmap),
        compressed=parse_bool(app_response_el, "bxd:Compressed", nsmap),
        compression_method=extract_text(app_response_el, "bxd:CompressionMethod", nsmap),
        amount_total=parse_float(app_response_el, "bxd:AmountTotal", nsmap),
        transaction_count=parse_int(app_response_el, "bxd:TransactionCount", nsmap),
        file_type=extract_text(app_response_el, "bxd:FileType", nsmap),
        content=_parse_content(app_response_el, nsmap),
    )


def parse_file_descriptors(response_element: etree._Element) -> list[dict]:
    """
    Extract FileDescriptors from ApplicationResponse.
    
    Returns a list of dicts with keys:
    - file_reference
    - file_type
    - status
    - service_id
    - user_filename
    - target_id
    """
    app_response_el = _extract_application_response_element(response_element)
    if app_response_el is None:
        return []
    
    nsmap = {"bxd": XMLDATA_NAMESPACE}
    descriptors = []
    
    file_descriptors_el = app_response_el.find("bxd:FileDescriptors", nsmap)
    if file_descriptors_el is None:
        return []
    
    for fd_el in file_descriptors_el.findall("bxd:FileDescriptor", nsmap):
        descriptor = {
            "file_reference": extract_text(fd_el, "bxd:FileReference", nsmap),
            "file_type": extract_text(fd_el, "bxd:FileType", nsmap),
            "status": extract_text(fd_el, "bxd:Status", nsmap),
            "service_id": extract_text(fd_el, "bxd:ServiceId", nsmap),
            "user_filename": extract_text(fd_el, "bxd:UserFilename", nsmap),
            "target_id": extract_text(fd_el, "bxd:TargetId", nsmap),
        }
        descriptors.append(descriptor)
    
    return descriptors


def _extract_application_response_element(element: etree._Element) -> Optional[etree._Element]:
    """
    Extract and decode the ApplicationResponse from a SOAP-wrapped response.

    The wire element (namespace http://model.bxd.fi) contains the real
    ApplicationResponse (namespace http://bxd.fi/xmldata/) as base64-encoded
    text, mirroring how outgoing ApplicationRequests are encoded.
    """
    wire_el = None
    if element.tag == f"{{{NS_SOAPENV}}}{TAG_ENVELOPE}":
        body = element.find(f"{{{NS_SOAPENV}}}{TAG_BODY}")
        if body is not None:
            for candidate in body.iter():
                if candidate.tag.endswith("}ApplicationResponse") or candidate.tag == "ApplicationResponse":
                    wire_el = candidate
                    break
    elif element.tag.endswith("}ApplicationResponse") or element.tag == "ApplicationResponse":
        wire_el = element

    if wire_el is None or not wire_el.text:
        return None

    try:
        decoded = base64.b64decode(wire_el.text)
        return etree.fromstring(decoded)
    except Exception:
        return None

def _parse_content(parent: etree._Element, nsmap: dict) -> Optional[bytes]:
    """
    Extract and base64-decode the Content element.
    
    The Content element contains base64-encoded data (possibly compressed).
    Returns the decoded bytes.
    """
    text = extract_text(parent, "bxd:Content", nsmap)
    if text:
        try:
            return base64.b64decode("".join(text.split()), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BankingProtocolError(
                "Nordea returned invalid base64 in ApplicationResponse content"
            ) from exc
    return None