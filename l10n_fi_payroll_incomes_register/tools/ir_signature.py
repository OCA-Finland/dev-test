# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import os
from datetime import timezone

import xmlsig
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12
from xmlsig.constants import (
    TransformEnveloped,
    TransformExclC14N,
    TransformRsaSha256,
    TransformSha256,
)

DS_NS = "http://www.w3.org/2000/09/xmldsig#"
DS_SIGNATURE = f"{{{DS_NS}}}Signature"


class IrSignatureError(Exception):
    """The Incomes Register signature check failed."""


def load_certificate_and_key(certificate_bytes, key_bytes=None, password=None):
    """Load a PEM or PKCS#12 certificate and its private key.

    A PEM file may contain the certificate alone. The key is then taken from
    ``key_bytes`` or from a second PEM block in the same file. PKCS#12 is used
    when the certificate file is not PEM.

    :param bytes certificate_bytes: PEM or PKCS#12 contents
    :param bytes key_bytes: optional PEM private key
    :param str password: password for PKCS#12 or an encrypted key
    :return: certificate and matching private key
    :rtype: tuple
    :raises ValueError: the file is not a readable certificate and key
    """
    password_bytes = password.encode() if isinstance(password, str) else password
    if certificate_bytes.lstrip().startswith(b"-----BEGIN"):
        certificate = _first_pem_certificate(certificate_bytes)
        private_key = None
        if key_bytes:
            private_key = serialization.load_pem_private_key(
                key_bytes, password=password_bytes
            )
        else:
            private_key = _pem_private_key(certificate_bytes, password_bytes)
        if certificate is None or private_key is None:
            raise ValueError("PEM certificate or private key is missing")
        return certificate, private_key
    try:
        private_key, certificate, _chain = pkcs12.load_key_and_certificates(
            certificate_bytes, password_bytes
        )
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise ValueError("PKCS#12 certificate could not be read") from exc
    if certificate is None or private_key is None:
        raise ValueError("PKCS#12 certificate or private key is missing")
    return certificate, private_key


def certificate_info(certificate):
    """Return the subject name and the expiry stored as a naive UTC datetime.

    Odoo datetimes are naive UTC. ``not_valid_after_utc`` is converted to that
    form so the expiry cron can compare it with ``fields.Datetime.now()``
    inside the UTC container.

    :param certificate: cryptography X.509 certificate
    :return: RFC 4514 subject and expiry
    :rtype: tuple(str, datetime.datetime)
    """
    expiry = certificate.not_valid_after_utc.astimezone(timezone.utc).replace(
        tzinfo=None, microsecond=0
    )
    return certificate.subject.rfc4514_string(), expiry


def sign_document(element, certificate, private_key):
    """Append an enveloped XML signature as the last child of ``element``.

    The signature uses RSA-SHA256, a SHA-256 digest, and Exclusive XML
    Canonicalization 1.0. The signing certificate is placed in
    ``KeyInfo/X509Data/X509Certificate``. The reference URI is empty, so it
    covers this element while it is the document root.

    :param lxml.etree._Element element: IR document to sign
    :param certificate: cryptography X.509 certificate
    :param private_key: cryptography private key
    :return: the same element, with the signature appended
    :rtype: lxml.etree._Element
    """
    for child in list(element):
        if child.tag == DS_SIGNATURE:
            element.remove(child)
    signature = xmlsig.template.create(
        TransformExclC14N, TransformRsaSha256, "Signature"
    )
    reference = xmlsig.template.add_reference(signature, TransformSha256, uri="")
    xmlsig.template.add_transform(reference, TransformEnveloped)
    xmlsig.template.add_transform(reference, TransformExclC14N)
    key_info = xmlsig.template.ensure_key_info(signature)
    xmlsig.template.x509_data_add_certificate(xmlsig.template.add_x509_data(key_info))
    element.append(signature)
    context = xmlsig.SignatureContext()
    context.x509 = certificate
    context.private_key = private_key
    context.public_key = certificate.public_key()
    context.sign(signature)
    return element


def verify_document(element, ca_bundle_pem):
    """Check the enveloped signature and that its certificate is in the bundle.

    ``xmlsig`` resolves an empty reference URI against the tree root. Call this
    with the IR document itself, not with the SOAP envelope wrapped around it.

    :param lxml.etree._Element element: signed IR document
    :param bytes ca_bundle_pem: PEM certificates trusted for the response
    :return: ``None``
    :rtype: None
    :raises IrSignatureError: the signature or the certificate is not trusted
    """
    signature = element[-1] if len(element) else None
    if signature is None or signature.tag != DS_SIGNATURE:
        raise IrSignatureError("The signature is not the last element.")
    context = xmlsig.SignatureContext()
    try:
        context.verify(signature)
    except Exception as exc:
        raise IrSignatureError("The signature is not valid.") from exc
    signer = _signer_certificate(signature)
    if not _certificate_is_trusted(signer, ca_bundle_pem):
        raise IrSignatureError("The signing certificate is not trusted.")


def _first_pem_certificate(payload):
    """Return the first certificate in a PEM payload.

    :param bytes payload: PEM text
    :return: certificate, or ``None`` when the payload has none
    :rtype: cryptography.x509.Certificate or None
    """
    marker = b"-----BEGIN CERTIFICATE-----"
    start = payload.find(marker)
    if start < 0:
        return None
    end = payload.find(b"-----END CERTIFICATE-----", start)
    if end < 0:
        return None
    end += len(b"-----END CERTIFICATE-----")
    return x509.load_pem_x509_certificate(payload[start:end])


def _pem_private_key(payload, password):
    """Return a private key embedded in a PEM payload.

    :param bytes payload: PEM text that may include a key
    :param bytes password: password for an encrypted key, or ``None``
    :return: private key, or ``None`` when the payload has none
    """
    for marker in (
        b"-----BEGIN PRIVATE KEY-----",
        b"-----BEGIN ENCRYPTED PRIVATE KEY-----",
    ):
        start = payload.find(marker)
        if start < 0:
            continue
        end_marker = marker.replace(b"BEGIN", b"END")
        end = payload.find(end_marker, start)
        if end < 0:
            continue
        block = payload[start : end + len(end_marker)]
        return serialization.load_pem_private_key(block, password=password)
    rsa_marker = b"-----BEGIN RSA PRIVATE KEY-----"
    start = payload.find(rsa_marker)
    if start < 0:
        return None
    end = payload.find(b"-----END RSA PRIVATE KEY-----", start)
    if end < 0:
        return None
    block = payload[start : end + len(b"-----END RSA PRIVATE KEY-----")]
    return serialization.load_pem_private_key(block, password=password)


def _signer_certificate(signature):
    """Read the first X509 certificate from a signature.

    :param lxml.etree._Element signature: ``ds:Signature`` element
    :return: signing certificate
    :rtype: cryptography.x509.Certificate
    :raises IrSignatureError: the signature has no certificate
    """
    node = signature.find(f".//{{{DS_NS}}}X509Certificate")
    if node is None or not (node.text or "").strip():
        raise IrSignatureError("The signature has no certificate.")
    der = base64.b64decode("".join(node.text.split()))
    return x509.load_der_x509_certificate(der)


def _certificate_is_trusted(certificate, ca_bundle_pem):
    """Return whether ``certificate`` is the bundle or is signed by it.

    A self-signed test certificate is trusted when the bundle contains that
    same certificate. A leaf is trusted when one bundle certificate is its
    issuer and the leaf signature verifies.

    :param certificate: cryptography X.509 certificate from the signature
    :param bytes ca_bundle_pem: PEM trust bundle
    :return: ``True`` when the certificate is trusted
    :rtype: bool
    """
    if not ca_bundle_pem:
        return False
    try:
        anchors = list(x509.load_pem_x509_certificates(ca_bundle_pem))
    except ValueError:
        return False
    fingerprint = certificate.fingerprint(hashes.SHA256())
    for anchor in anchors:
        if anchor.fingerprint(hashes.SHA256()) == fingerprint:
            return True
    for issuer in anchors:
        if certificate.issuer != issuer.subject:
            continue
        try:
            issuer.public_key().verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                padding.PKCS1v15(),
                certificate.signature_hash_algorithm,
            )
        except Exception:
            continue
        return True
    return False


def write_private_file(path, payload):
    """Write ``payload`` to ``path`` with mode 0600.

    :param str path: destination path
    :param bytes payload: file contents
    :return: ``None``
    :rtype: None
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
