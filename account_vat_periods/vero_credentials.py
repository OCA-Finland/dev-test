"""Private Linux storage and Vero PKI enrollment, independent of ORM rollback.

No transfer password is persisted. Never log inputs, HTTP bodies or exceptions.
Only verified XML payloads are consumed; trust is limited to the bundled Vero CAs.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
import requests
from signxml import XMLVerifier, SignatureConfiguration

from .vero_payload import PayloadError, _

NS = 'http://certificates.vero.fi/2017/10/certificateservices'
SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
DS = 'http://www.w3.org/2000/09/xmldsig#'
ENDPOINTS = {
    'test': 'https://pkiws-testi.vero.fi/2017/10/CertificateServices',
    'production': 'https://pkiws.vero.fi/2017/10/CertificateServices',
}
CA_DIRECTORY = Path(__file__).parent / 'data' / 'vero_ca'
MAX_RESPONSE = 1024 * 1024


class CredentialError(PayloadError):
    """Only fixed, safe messages; never third-party exception text."""


def private_directory(path):
    path = Path(path)
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise CredentialError(_('The private directory permissions or owner are invalid.'))
    return path


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise CredentialError(_('The secret file permissions or type are invalid.'))
        data = stream.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise CredentialError(_('The secret file is too large.'))
        return data


def save_private(path, data):
    # New inode + atomic replacement: no writes through symlinks or hard links.
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(directory):
    fd = os.open(directory / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise CredentialError(_('The certificate lock file is not secure.'))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CredentialError(_('Another credential operation is in progress. Refresh the status shortly.')) from None
        yield
    finally:
        os.close(fd)


def chain_verify(cert, environment, kind):
    """OpenSSL validates the complete chain, dates and CA constraints."""
    if environment not in ENDPOINTS or kind not in ('providers', 'services'):
        raise CredentialError(_('Unknown certificate environment.'))
    result = subprocess.run([
        'openssl', 'verify', '-no-CApath', '-no-CAstore',
        '-CAfile', str(CA_DIRECTORY / f'{environment}-{kind}-root.pem'),
        '-untrusted', str(CA_DIRECTORY / f'{environment}-{kind}-chain.pem'),
        '-purpose', 'sslclient' if kind == 'providers' else 'any',
    ], input=cert.public_bytes(serialization.Encoding.PEM), capture_output=True, timeout=10)
    issuers = x509.load_pem_x509_certificates((CA_DIRECTORY / f'{environment}-{kind}-chain.pem').read_bytes())
    if result.returncode or not any(cert.issuer == ca.subject and 'Issuing' in ca.subject.rfc4514_string() for ca in issuers):
        raise CredentialError(_('The certificate trust chain could not be verified for the selected environment.'))
    if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise CredentialError(_('The service returned an invalid CA certificate.'))


def verified_response(content, operation, environment):
    if len(content) > MAX_RESPONSE or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise CredentialError(_('The certificate service XML response is not secure.'))
    try:
        root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
        nodes = root.findall('./{%s}Body/{%s}%sResponse' % (SOAP, NS, operation))
        if root.tag != '{%s}Envelope' % SOAP or len(nodes) != 1:
            raise ValueError()
        payload = nodes[0]
        certificates = payload.findall('./{%s}Signature/{%s}KeyInfo/{%s}X509Data/{%s}X509Certificate' % ((DS,) * 4))
        if len(certificates) != 1:
            raise ValueError()
        signer = x509.load_der_x509_certificate(base64.b64decode(''.join(certificates[0].text.split()), validate=True))
        chain_verify(signer, environment, 'services')
        # Vero signs the application document before adding its SOAP envelope.
        # Preserve ALL application namespaces (including the ds prefix), but
        # remove the inherited transport declaration before inclusive C14N.
        document = re.sub(rb' xmlns:[A-Za-z_][\w.-]*="http://schemas.xmlsoap.org/soap/envelope/"',
                          b'', etree.tostring(payload))
        verified = XMLVerifier().verify(document, x509_cert=signer,
            expect_config=SignatureConfiguration(location='./', expect_references=1)).signed_xml
        if verified.tag != payload.tag:
            raise ValueError()
        return verified
    except CredentialError:
        raise
    except Exception:
        raise CredentialError(_('The certificate service response signature or structure could not be verified.')) from None


def call_pki(operation, fields, environment, response_path):
    root = etree.Element('{%s}Envelope' % SOAP, nsmap={'soapenv': SOAP, 'cer': NS})
    etree.SubElement(root, '{%s}Header' % SOAP)
    body = etree.SubElement(root, '{%s}Body' % SOAP)
    request = etree.SubElement(body, '{%s}%sRequest' % (NS, operation))
    for name, value in fields:
        etree.SubElement(request, name).text = value
    try:
        with requests.Session() as session:
            # Ignore netrc/proxy environment to prevent credential forwarding.
            session.trust_env = False
            with session.post(ENDPOINTS[environment], data=etree.tostring(root, encoding='utf-8', xml_declaration=True),
                headers={'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': '"%s"' % (operation[0].lower() + operation[1:])},
                timeout=(10, 45), allow_redirects=False, stream=True) as response:
                content = bytearray()
                for chunk in response.iter_content(16384):
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE:
                        raise CredentialError(_('The certificate service response is too large.'))
                if response.status_code != 200:
                    raise CredentialError(_('The certificate service HTTP request failed. Check the retrieval status.'))
    except requests.RequestException:
        raise CredentialError(_('The certificate service connection was interrupted or timed out. Check the retrieval status.')) from None
    save_private(response_path, bytes(content))
    return verified_response(bytes(content), operation, environment)


class Enrollment:
    def __init__(self, directory, environment, identity, actor):
        self.directory, self.environment, self.identity, self.actor = directory, environment, identity, actor

    def state(self):
        path = self.directory / 'enrollment.json'
        return json.loads(read_private(path)) if path.exists() else {}

    def save(self, state):
        state.update(updated_at=datetime.now(timezone.utc).isoformat(), updated_by=self.actor)
        save_private(self.directory / 'enrollment.json', json.dumps(state).encode())

    def generation(self, state):
        token = state.get('generation', '')
        if not re.fullmatch('[a-f0-9]{32}', token):
            raise CredentialError(_('The certificate retrieval state is invalid.'))
        return private_directory(self.directory / token)

    def common(self, state):
        return [('Environment', self.environment.upper()), ('CustomerId', state['identity']), ('CustomerName', state['customer_name'])]

    def recover(self, state):
        if state.get('phase') == 'uncertain':
            response = self.generation(state) / 'submit-response.xml'
            if response.exists():
                self.accept_response(state, verified_response(read_private(response), 'SignNewCertificate', self.environment))
        return state

    def accept_response(self, state, payload):
        if payload.findtext('./Result/Status') == 'FAIL':
            codes = [n.text for n in payload.findall('./Result/ErrorInfo/ErrorCode') if re.fullmatch(r'PKI\d{3}', n.text or '')]
            state.update(phase='rejected', message='The Finnish Tax Administration rejected the request: ' + ', '.join(codes))
        elif payload.findtext('./Result/Status') == 'OK' and re.fullmatch(r'[A-Za-z0-9-]{1,32}', payload.findtext('RetrievalId') or ''):
            state.update(phase='waiting', retrieval_id=payload.findtext('RetrievalId'), ready_after=time.time() + 30, message='Request received. Wait at least 30 seconds, then retrieve the certificate.')
        else:
            raise CredentialError(_('The response has no retrieval identifier. No new request was sent.'))
        self.save(state)

    def submit(self, transfer_id, password, customer_name):
        if self.environment not in ENDPOINTS:
            raise CredentialError(_('Sandbox does not use a certificate.'))
        if not isinstance(transfer_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,32}', transfer_id):
            raise CredentialError(_('Check the transfer identifier (maximum 32 characters).'))
        if not isinstance(password, str) or not 1 <= len(password) <= 16 or any(ord(c) < 33 or ord(c) > 126 for c in password):
            raise CredentialError(_('Check the one-time password (maximum 16 characters).'))
        old = self.recover(self.state())
        if old.get('phase') in ('uncertain', 'waiting', 'ready'):
            raise CredentialError(_('A previous certificate request is pending. Refresh the status and continue retrieving the same certificate.'))
        token = uuid.uuid4().hex
        directory = private_directory(self.directory / token)
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, 'FI'),
            x509.NameAttribute(NameOID.COMMON_NAME, self.identity),
        ])).sign(key, hashes.SHA256())
        save_private(directory / 'private-key.pem', key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        save_private(directory / 'request.csr', csr.public_bytes(serialization.Encoding.PEM))
        state = {'generation': token, 'identity': self.identity, 'customer_name': customer_name[:100],
                 'phase': 'uncertain', 'message': 'The request has started. If no response is available, verify the outcome with the Finnish Tax Administration before trying again.'}
        # Durable marker BEFORE sending one-use credentials, even if ORM rolls back.
        self.save(state)
        fields = self.common(state) + [('TransferId', transfer_id), ('TransferPassword', password),
            ('CertificateRequest', base64.b64encode(csr.public_bytes(serialization.Encoding.DER)).decode())]
        payload = call_pki('SignNewCertificate', fields, self.environment, directory / 'submit-response.xml')
        self.accept_response(state, payload)

    def retrieve(self):
        state = self.recover(self.state())
        if state.get('phase') not in ('waiting', 'ready', 'active'):
            raise CredentialError(_('The certificate request has no confirmed retrieval identifier.'))
        if self.identity != state['identity']:
            raise CredentialError(_('The company identifier has changed since the certificate request.'))
        directory = self.generation(state)
        if state['phase'] == 'waiting':
            if time.time() < state['ready_after']:
                raise CredentialError(_('Wait at least 30 seconds after requesting the certificate.'))
            payload = call_pki('GetCertificate', self.common(state) + [('RetrievalId', state['retrieval_id'])], self.environment, directory / 'retrieve-response.xml')
            if payload.findtext('./Result/Status') != 'OK':
                raise CredentialError(_('The certificate is not available yet. Try retrieval later using the same request.'))
            try:
                cert = x509.load_der_x509_certificate(base64.b64decode(''.join(payload.findtext('Certificate').split()), validate=True))
            except Exception:
                raise CredentialError(_('The response does not contain a valid certificate.')) from None
            key = serialization.load_pem_private_key(read_private(directory / 'private-key.pem'), password=None)
            self.validate(cert, key)
            save_private(directory / 'certificate.pem', cert.public_bytes(serialization.Encoding.PEM))
            state.update(phase='ready', message='Certificate verified and ready for activation.',
                         expires=cert.not_valid_after_utc.isoformat(), fingerprint=cert.fingerprint(hashes.SHA256()).hex())
            self.save(state)
        cert = x509.load_pem_x509_certificate(read_private(directory / 'certificate.pem'))
        key = serialization.load_pem_private_key(read_private(directory / 'private-key.pem'), password=None)
        self.validate(cert, key)
        return state, directory

    def validate(self, cert, key):
        chain_verify(cert, self.environment, 'providers')
        common_names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if len(common_names) != 1 or common_names[0].value != self.identity or cert.public_key().public_numbers() != key.public_key().public_numbers():
            raise CredentialError(_('The certificate does not match the company identifier or the key generated on the server.'))

    def status(self):
        state = self.recover(self.state())
        return {key: state[key] for key in ('phase', 'message', 'expires', 'fingerprint', 'updated_at', 'updated_by', 'identity') if key in state}
