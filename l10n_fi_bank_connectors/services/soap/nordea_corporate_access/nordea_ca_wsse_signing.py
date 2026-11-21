import base64
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.serialization import Encoding
from cryptography import x509
from lxml import etree
from signxml import XMLSigner, methods

from ...constants.crypto import RSA_SHA256, SHA256
from ...constants.xml_namespaces import C14N_EXCLUSIVE, NS_DS
from .constants.namespaces import NS_PREFIX_WSSE, NS_PREFIX_WSU, NS_SOAPENV, NS_WSSE, NS_WSU
from .constants.soap_envelope import TAG_BODY, TAG_SOAP_HEADER
from .constants.wsse_security import (
    TAG_SECURITY, TAG_TIMESTAMP, TAG_CREATED, TAG_EXPIRES,
    TAG_BINARY_SECURITY_TOKEN, TAG_ID,
    TAG_SECURITY_TOKEN_REFERENCE, TAG_REFERENCE, TAG_KEY_INFO,
    ATTR_VALUE_TYPE, ATTR_ENCODING_TYPE, ATTR_URI, ATTR_MUST_UNDERSTAND,
    MUST_UNDERSTAND_TRUE, WSU_ID_PREFIX,
    VALUE_TYPE_X509V3, ENCODING_TYPE_BASE64,
    TIMESTAMP_VALIDITY_SECONDS,
)
from ....utils.clock import utc_now


def sign_envelope(envelope: etree._Element, cert_pem: str, key_pem: str) -> etree._Element:
    """
    Add a wsse:Security SOAP header to `envelope`, signing the existing
    soapenv:Body and a new wsu:Timestamp (two-reference detached XML-dsig,
    per Nordea's Web Services Security and Communication Description 7.5/7.6).
    KeyInfo references the BinarySecurityToken via SecurityTokenReference,
    matching Nordea's own example, rather than signxml's default X509Data.
    Mutates and returns `envelope`.
    """
    body_el = envelope.find(f"{{{NS_SOAPENV}}}{TAG_BODY}")
    if body_el is None:
        raise ValueError("sign_envelope: envelope has no soapenv:Body")

    body_id = f"{WSU_ID_PREFIX}{uuid.uuid4().hex}"
    body_el.set(f"{{{NS_WSU}}}{TAG_ID}", body_id)

    header_el = etree.Element(f"{{{NS_SOAPENV}}}{TAG_SOAP_HEADER}")
    envelope.insert(0, header_el)

    security_el = etree.SubElement(
        header_el, f"{{{NS_WSSE}}}{TAG_SECURITY}", nsmap={NS_PREFIX_WSSE: NS_WSSE}
    )
    security_el.set(f"{{{NS_SOAPENV}}}{ATTR_MUST_UNDERSTAND}", MUST_UNDERSTAND_TRUE)

    timestamp_id = f"{WSU_ID_PREFIX}{uuid.uuid4().hex}"
    timestamp_el = etree.SubElement(
        security_el, f"{{{NS_WSU}}}{TAG_TIMESTAMP}", nsmap={NS_PREFIX_WSU: NS_WSU}
    )
    timestamp_el.set(f"{{{NS_WSU}}}{TAG_ID}", timestamp_id)
    now = utc_now()
    etree.SubElement(timestamp_el, f"{{{NS_WSU}}}{TAG_CREATED}").text = _iso(now)
    etree.SubElement(timestamp_el, f"{{{NS_WSU}}}{TAG_EXPIRES}").text = _iso(
        now + timedelta(seconds=TIMESTAMP_VALIDITY_SECONDS)
    )

    bst_id = f"{WSU_ID_PREFIX}{uuid.uuid4().hex}"
    bst_el = etree.SubElement(security_el, f"{{{NS_WSSE}}}{TAG_BINARY_SECURITY_TOKEN}")
    bst_el.set(ATTR_VALUE_TYPE, VALUE_TYPE_X509V3)
    bst_el.set(ATTR_ENCODING_TYPE, ENCODING_TYPE_BASE64)
    bst_el.set(f"{{{NS_WSU}}}{TAG_ID}", bst_id)
    bst_el.text = base64.b64encode(_cert_der(cert_pem)).decode()

    signer = XMLSigner(
        method=methods.detached,
        signature_algorithm=RSA_SHA256,
        digest_algorithm=SHA256,
        c14n_algorithm=C14N_EXCLUSIVE,
    )
    signature_el = signer.sign(
        data=envelope,
        reference_uri=[timestamp_id, body_id],
        key=key_pem,
    )

    # TODO needs to be fixed better
    # signxml auto-generates <ds:KeyInfo> (RSAKeyValue, since no cert= was passed to sign()),
    # and then SecurityTokenReference adds another one
    # so here we are removing the generated one but could probably be resolved better
    for existing_key_info in signature_el.findall(f"{{{NS_DS}}}{TAG_KEY_INFO}"):
        signature_el.remove(existing_key_info)

    key_info_el = etree.SubElement(signature_el, f"{{{NS_DS}}}{TAG_KEY_INFO}")
    str_el = etree.SubElement(
        key_info_el, f"{{{NS_WSSE}}}{TAG_SECURITY_TOKEN_REFERENCE}", nsmap={NS_PREFIX_WSSE: NS_WSSE}
    )
    ref_el = etree.SubElement(str_el, f"{{{NS_WSSE}}}{TAG_REFERENCE}")
    ref_el.set(ATTR_URI, f"#{bst_id}")
    ref_el.set(ATTR_VALUE_TYPE, VALUE_TYPE_X509V3)

    security_el.append(signature_el)

    return envelope


def _cert_der(cert_pem: str) -> bytes:
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    return cert.public_bytes(Encoding.DER)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Expected a timezone-aware datetime.")

    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"