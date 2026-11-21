import logging

from lxml import etree
from signxml import XMLSigner, methods, XMLVerifier

from ...services.constants.crypto import RSA_SHA256, SHA256
from ...services.constants.xml_namespaces import C14N_INCLUSIVE_WITH_COMMENTS, NS_DS

_logger = logging.getLogger(__name__)


def sign_xml_enveloped(element: etree._Element, private_key_pem: str, cert_pem: str,) -> etree._Element:
    """
    Sign an lxml element per XML-dsig, enveloped method, RSA-SHA256.
    Returns a new element with a <Signature> embedded inside it.
    """
    try:
        signer = XMLSigner(
            method=methods.enveloped,
            signature_algorithm=RSA_SHA256,
            digest_algorithm=SHA256,
            c14n_algorithm=C14N_INCLUSIVE_WITH_COMMENTS,
        )
        return signer.sign(element, key=private_key_pem, cert=cert_pem)
    except Exception as e:
        _logger.error("Failed to sign XML element: %s", e)
        raise ValueError("Failed to sign XML element.") from e


def verify_xml_enveloped_signature(element: etree._Element) -> bool:
    """
    Verify an enveloped XML-dsig <Signature> is cryptographically valid
    against the certificate embedded in the same element (KeyInfo/X509Data).
    """
    cert_el = element.find(f".//{{{NS_DS}}}X509Certificate")
    if cert_el is None or not cert_el.text:
        _logger.warning("XML signature verification failed: no embedded X509Certificate found")
        return False

    embedded_cert_pem = (
        "-----BEGIN CERTIFICATE-----\n" + cert_el.text.strip() + "\n-----END CERTIFICATE-----"
    )

    try:
        XMLVerifier().verify(element, x509_cert=embedded_cert_pem)
        return True
    except Exception as e:
        _logger.warning("XML signature verification failed: %s", e)
        return False