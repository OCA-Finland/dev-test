import base64

from lxml import etree

from .constants.namespaces import XMLDATA_NAMESPACE, NS_PREFIX_XMLDATA
from .constants.application_request import (
    TAG_APPLICATION_REQUEST, TAG_CUSTOMER_ID, TAG_COMMAND,
    TAG_TIMESTAMP, TAG_START_DATE, TAG_END_DATE, TAG_STATUS, TAG_SERVICE_ID,
    TAG_ENVIRONMENT, TAG_FILE_REFERENCES, TAG_FILE_REFERENCE,
    TAG_USER_FILENAME, TAG_TARGET_ID, TAG_EXECUTION_SERIAL, TAG_ENCRYPTION,
    TAG_ENCRYPTION_METHOD, TAG_COMPRESSION, TAG_COMPRESSION_METHOD,
    TAG_SOFTWARE_ID, TAG_FILE_TYPE, TAG_CONTENT,
)
from .nordea_ca_dtos import ApplicationRequestDTO
from ....utils.soap.xml_signing import sign_xml_enveloped


def build_application_request(dto: ApplicationRequestDTO) -> etree._Element:
    """
    Build an unsigned <ApplicationRequest> element from an ApplicationRequestDTO.
    see schema https://www.nordea.fi/Images/146-88693/ApplicationRequest.zip
    """
    root = etree.Element("{%s}%s" % (XMLDATA_NAMESPACE, TAG_APPLICATION_REQUEST), nsmap={NS_PREFIX_XMLDATA: XMLDATA_NAMESPACE})

    def add(tag: str, value):
        if value is None:
            return
        el = etree.SubElement(root, "{%s}%s" % (XMLDATA_NAMESPACE, tag))
        el.text = str(value)

    add(TAG_CUSTOMER_ID, dto.customer_id)
    add(TAG_COMMAND, dto.command)
    add(TAG_TIMESTAMP, dto.timestamp.isoformat() if dto.timestamp else None)
    add(TAG_START_DATE, dto.start_date.isoformat() if dto.start_date else None)
    add(TAG_END_DATE, dto.end_date.isoformat() if dto.end_date else None)
    add(TAG_STATUS, dto.status)
    add(TAG_SERVICE_ID, dto.service_id)
    add(TAG_ENVIRONMENT, dto.environment)

    if dto.file_references:
        refs_el = etree.SubElement(root, "{%s}%s" % (XMLDATA_NAMESPACE, TAG_FILE_REFERENCES))
        for ref in dto.file_references:
            ref_el = etree.SubElement(refs_el, "{%s}%s" % (XMLDATA_NAMESPACE, TAG_FILE_REFERENCE))
            ref_el.text = ref

    add(TAG_USER_FILENAME, dto.user_filename)
    add(TAG_TARGET_ID, dto.target_id)
    add(TAG_EXECUTION_SERIAL, dto.execution_serial)
    add(TAG_ENCRYPTION, "true" if dto.encryption else "false" if dto.encryption is not None else None)
    add(TAG_ENCRYPTION_METHOD, dto.encryption_method)
    add(TAG_COMPRESSION, "true" if dto.compression else "false" if dto.compression is not None else None)
    add(TAG_COMPRESSION_METHOD, dto.compression_method)
    add(TAG_SOFTWARE_ID, dto.software_id)
    add(TAG_FILE_TYPE, dto.file_type)

    if dto.content is not None:
        content_el = etree.SubElement(root, "{%s}%s" % (XMLDATA_NAMESPACE, TAG_CONTENT))
        content_el.text = base64.b64encode(dto.content).decode()

    return root

def sign_application_request(element: etree._Element, private_key_pem: str, cert_pem: str,) -> etree._Element:
    """
    Sign a built <ApplicationRequest> element per Nordea's Secure Envelope
    spec — enveloped XML-dsig, RSA-SHA256. Returns the element with a
    <Signature> embedded (the "locked" ApplicationRequest).
    """
    return sign_xml_enveloped(element, private_key_pem, cert_pem)
