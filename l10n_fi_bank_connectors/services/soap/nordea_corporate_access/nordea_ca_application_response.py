import base64
from lxml import etree

from .constants.namespaces import XMLDATA_NAMESPACE
from .constants.application_response import (
    TAG_CUSTOMER_ID, TAG_TIMESTAMP, TAG_RESPONSE_CODE,
    TAG_RESPONSE_TEXT, TAG_EXECUTION_SERIAL, TAG_ENCRYPTED,
    TAG_ENCRYPTION_METHOD, TAG_COMPRESSED, TAG_COMPRESSION_METHOD,
    TAG_AMOUNT_TOTAL, TAG_TRANSACTION_COUNT, TAG_FILE_TYPE, TAG_CONTENT,
)
from .nordea_ca_dtos import ApplicationResponseDTO


def _text(element: etree._Element, tag: str) -> str | None:
    el = element.find(f"{{{XMLDATA_NAMESPACE}}}{tag}")
    return el.text if el is not None else None


def _bool(element: etree._Element, tag: str) -> bool | None:
    val = _text(element, tag)
    if val is None:
        return None
    return val.strip().lower() == "true"


def parse_application_response(element: etree._Element) -> ApplicationResponseDTO:
    """
    Parse a top-level <ApplicationResponse> element into an
    ApplicationResponseDTO. Content is base64-decoded to raw bytes;
    decompression (if Compressed=true) is NOT done here.
    """
    content_text = _text(element, TAG_CONTENT)
    amount_total = _text(element, TAG_AMOUNT_TOTAL)
    transaction_count = _text(element, TAG_TRANSACTION_COUNT)

    return ApplicationResponseDTO(
        customer_id=_text(element, TAG_CUSTOMER_ID),
        timestamp=_text(element, TAG_TIMESTAMP),
        response_code=_text(element, TAG_RESPONSE_CODE),
        response_text=_text(element, TAG_RESPONSE_TEXT),
        execution_serial=_text(element, TAG_EXECUTION_SERIAL),
        encrypted=_bool(element, TAG_ENCRYPTED),
        encryption_method=_text(element, TAG_ENCRYPTION_METHOD),
        compressed=_bool(element, TAG_COMPRESSED),
        compression_method=_text(element, TAG_COMPRESSION_METHOD),
        amount_total=float(amount_total) if amount_total is not None else None,
        transaction_count=int(transaction_count) if transaction_count is not None else None,
        file_type=_text(element, TAG_FILE_TYPE),
        content=base64.b64decode(content_text) if content_text is not None else None,
    )