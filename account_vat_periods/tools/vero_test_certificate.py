#!/usr/bin/env python3
"""Retrieve a Vero TEST certificate on Linux; never sends to production.

Run with the Odoo Python environment. Secrets and state stay outside the repo.
Actions: prepare, submit (one attempt only), retrieve (safe to repeat), status.
Requires requests and cryptography. Does not implement certificate renewal.
"""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ENDPOINT = 'https://pkiws-testi.vero.fi/2017/10/CertificateServices'
NS = 'http://certificates.vero.fi/2017/10/certificateservices'
SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
ET.register_namespace('soapenv', SOAP)
ET.register_namespace('cer', NS)


class SafeError(Exception):
    """Only fixed, non-secret messages may be passed to this exception."""


def save(path, content):
    """Atomic, private, durable write; do not expose partially written state."""
    temporary = path.with_name(path.name + '.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def envelope(operation, fields):
    root = ET.Element('{%s}Envelope' % SOAP)
    ET.SubElement(root, '{%s}Header' % SOAP)
    body = ET.SubElement(root, '{%s}Body' % SOAP)
    request = ET.SubElement(body, '{%s}%sRequest' % (NS, operation))
    for name, value in fields:
        if not value:
            raise SafeError('Empty request field.')
        ET.SubElement(request, name).text = value
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def call(operation, fields, response_path):
    # No redirect, HTTP retry or request/body logging: the transfer password is one-use.
    response = requests.post(
        ENDPOINT, data=envelope(operation, fields),
        headers={'Content-Type': 'text/xml; charset=utf-8',
                 'SOAPAction': '"%s"' % (operation[0].lower() + operation[1:])},
        timeout=(10, 45), allow_redirects=False,
    )
    save(response_path, response.content)
    if response.status_code != 200:
        raise SafeError('PKI HTTP error %s; protected response saved.' % response.status_code)
    return parse_response(response.content, operation)


def parse_response(content, operation):
    if len(content) > 1024 * 1024 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise SafeError('Unsafe PKI response.')
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise SafeError('PKI response is not valid XML.') from None
    payload = root.find('./{%s}Body/{%s}%sResponse' % (SOAP, NS, operation))
    if payload is None:
        raise SafeError('Unexpected SOAP response; protected response saved.')
    if payload.findtext('./Result/Status') != 'OK':
        codes = [e.text or '' for e in payload.findall('./Result/ErrorInfo/ErrorCode')]
        codes = [c for c in codes if re.fullmatch(r'PKI\d{3}', c)]
        raise SafeError('PKI rejected request: ' + (', '.join(codes) or 'unspecified error'))
    return payload


def validate_certificate(cert, key, customer_id):
    if cert.public_key().public_numbers() != key.public_key().public_numbers():
        raise SafeError('Certificate does not match the saved private key.')
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(names) != 1 or names[0].value != customer_id:
        raise SafeError('Certificate does not match the requested customer.')
    now = datetime.now(timezone.utc)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        raise SafeError('Certificate is not currently valid.')
    issuer = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(issuer) != 1 or issuer[0].value != 'Data Providers Test Issuing CA v1':
        raise SafeError('Certificate is not issued by the expected TEST issuer.')


def prepare(directory, customer_id, customer_name):
    if any((directory / n).exists() for n in ['private-key.pem', 'request.csr', 'identity.json', 'submit-started.json']):
        raise SafeError('Existing enrollment files: use status; never replace its private key.')
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, 'FI'),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, customer_name),
        x509.NameAttribute(NameOID.COMMON_NAME, customer_id),
    ])
    csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, hashes.SHA256())
    save(directory / 'private-key.pem', key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    save(directory / 'request.csr', csr.public_bytes(serialization.Encoding.PEM))
    save(directory / 'identity.json', json.dumps({'customer_id': customer_id, 'customer_name': customer_name}).encode())
    print('Prepared: RSA 3072 key and CSR stored privately on this server.')


def common_fields(identity):
    return [('Environment', 'TEST'), ('CustomerId', identity['customer_id']), ('CustomerName', identity['customer_name'])]


def run(args):
    directory = Path(args.directory)
    if not directory.is_absolute():
        raise SafeError('Enrollment directory must be absolute.')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise SafeError('Enrollment directory must be owned by this user and mode 0700.')
    lock = os.open(directory / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'prepare':
            if not args.customer_id or not args.customer_name:
                raise SafeError('Customer ID and name are required for prepare.')
            return prepare(directory, args.customer_id, args.customer_name)
        identity = json.loads((directory / 'identity.json').read_text())
        if args.action == 'status':
            print(json.dumps({'customer_id': identity['customer_id'], 'environment': 'TEST',
                              'submitted': (directory / 'submit-started.json').exists(),
                              'retrieval_id_saved': (directory / 'retrieval.json').exists(),
                              'certificate_saved': (directory / 'certificate.pem').exists()}))
            return
        key = serialization.load_pem_private_key((directory / 'private-key.pem').read_bytes(), password=None)
        if args.action == 'submit':
            if (directory / 'submit-started.json').exists():
                raise SafeError('Submission already attempted. Recover saved response; do not consume credentials again.')
            if not args.credentials_file:
                raise SafeError('A private credentials JSON file is required.')
            credentials = json.loads(Path(args.credentials_file).read_text())
            if credentials['customer_id'] != identity['customer_id']:
                raise SafeError('Credential customer ID mismatch.')
            csr = x509.load_pem_x509_csr((directory / 'request.csr').read_bytes())
            if not csr.is_signature_valid or csr.public_key().public_numbers() != key.public_key().public_numbers():
                raise SafeError('Saved CSR does not match the private key.')
            fields = common_fields(identity) + [
                ('TransferId', credentials['transfer_id']), ('TransferPassword', credentials['transfer_password']),
                ('CertificateRequest', base64.b64encode(csr.public_bytes(serialization.Encoding.DER)).decode()),
            ]
            # Validate serialization before marking the one-time attempt.
            envelope('SignNewCertificate', fields)
            save(directory / 'submit-started.json', json.dumps({'time': time.time()}).encode())
            payload = call('SignNewCertificate', fields, directory / 'submit-response.xml')
            retrieval = payload.findtext('RetrievalId')
            if not retrieval or not re.fullmatch(r'[A-Za-z0-9-]{1,32}', retrieval):
                raise SafeError('Missing/invalid retrieval ID; inspect protected response.')
            save(directory / 'retrieval.json', json.dumps({'id': retrieval, 'time': time.time()}).encode())
            print('Request accepted; retrieval ID saved. Wait at least 30 seconds, then retrieve.')
            return
        state = json.loads((directory / 'retrieval.json').read_text())
        if time.time() - state['time'] < 30:
            raise SafeError('Wait at least 30 seconds after submission before retrieving.')
        if (directory / 'certificate.pem').exists():
            raise SafeError('Certificate already saved. No request sent.')
        payload = call('GetCertificate', common_fields(identity) + [('RetrievalId', state['id'])], directory / 'retrieve-response.xml')
        encoded = ''.join((payload.findtext('Certificate') or '').split())
        cert = x509.load_der_x509_certificate(base64.b64decode(encoded, validate=True))
        validate_certificate(cert, key, identity['customer_id'])
        save(directory / 'certificate.pem', cert.public_bytes(serialization.Encoding.PEM))
        print(json.dumps({'certificate': str(directory / 'certificate.pem'),
                          'valid_until': cert.not_valid_after_utc.isoformat(),
                          'sha256': cert.fingerprint(hashes.SHA256()).hex()}))
    finally:
        os.close(lock)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'submit', 'retrieve', 'status'])
    parser.add_argument('--directory', required=True)
    parser.add_argument('--customer-id')
    parser.add_argument('--customer-name')
    parser.add_argument('--credentials-file')
    args = parser.parse_args()
    try:
        run(args)
    except SafeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        # Third-party exception messages may echo secrets: show only the class.
        print('Stopped (%s). Private state retained; no automatic submission retry.' % type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
