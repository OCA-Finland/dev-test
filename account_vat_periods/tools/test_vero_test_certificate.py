"""Offline safety tests: run on Linux with python -m unittest discover -s tools."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import requests
import vero_test_certificate as pki


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        pki.prepare(self.directory, '0123456-7', 'Example & Co')
        self.key = serialization.load_pem_private_key((self.directory / 'private-key.pem').read_bytes(), None)
        self.credentials = self.directory / 'credentials.json'
        pki.save(self.credentials, json.dumps({'customer_id': '0123456-7', 'transfer_id': 'fake', 'transfer_password': 'fake'}).encode())

    def args(self, action):
        return argparse.Namespace(action=action, directory=str(self.directory), customer_id=None, customer_name=None, credentials_file=str(self.credentials))

    def test_prepare_never_overwrites_key(self):
        before = (self.directory / 'private-key.pem').read_bytes()
        with self.assertRaises(pki.SafeError):
            pki.prepare(self.directory, '0123456-7', 'Example')
        self.assertEqual(before, (self.directory / 'private-key.pem').read_bytes())
        self.assertEqual((self.directory / 'private-key.pem').stat().st_mode & 0o777, 0o600)

    def test_csr_matches_key(self):
        csr = x509.load_pem_x509_csr((self.directory / 'request.csr').read_bytes())
        self.assertTrue(csr.is_signature_valid)
        self.assertEqual(csr.public_key().public_numbers(), self.key.public_key().public_numbers())

    def test_xml_escaping(self):
        raw = pki.envelope('SignNewCertificate', [('TransferPassword', 'a<&>b')])
        root = ET.fromstring(raw)
        self.assertEqual(root.findtext('.//TransferPassword'), 'a<&>b')

    def test_fail_response_not_accepted_or_echoed(self):
        raw = ('<s:Envelope xmlns:s="%s"><s:Body><c:SignNewCertificateResponse xmlns:c="%s">'
               '<Result><Status>FAIL</Status><ErrorInfo><ErrorCode>PKI020</ErrorCode>'
               '<ErrorMessage>secret-value</ErrorMessage></ErrorInfo></Result>'
               '</c:SignNewCertificateResponse></s:Body></s:Envelope>') % (pki.SOAP, pki.NS)
        with self.assertRaises(pki.SafeError) as caught:
            pki.parse_response(raw.encode(), 'SignNewCertificate')
        self.assertIn('PKI020', str(caught.exception))
        self.assertNotIn('secret-value', str(caught.exception))

    def test_timeout_prevents_second_submission(self):
        with patch.object(pki.requests, 'post', side_effect=requests.Timeout('secret-value')) as post:
            with self.assertRaises(requests.Timeout):
                pki.run(self.args('submit'))
            with self.assertRaises(pki.SafeError):
                pki.run(self.args('submit'))
        self.assertEqual(post.call_count, 1)
        self.assertTrue((self.directory / 'submit-started.json').exists())
        self.assertTrue((self.directory / 'private-key.pem').exists())

    def test_customer_mismatch_never_sends(self):
        pki.save(self.credentials, json.dumps({'customer_id': '7654321-0'}).encode())
        with patch.object(pki.requests, 'post') as post:
            with self.assertRaises(pki.SafeError):
                pki.run(self.args('submit'))
            post.assert_not_called()
        self.assertFalse((self.directory / 'submit-started.json').exists())

    def test_retrieve_too_early_never_sends(self):
        pki.save(self.directory / 'retrieval.json', json.dumps({'id': 'fake', 'time': pki.time.time()}).encode())
        with patch.object(pki.requests, 'post') as post:
            with self.assertRaises(pki.SafeError):
                pki.run(self.args('retrieve'))
            post.assert_not_called()

    def test_certificate_key_customer_expiry_and_issuer(self):
        def make_cert(key, customer='0123456-7', issuer='Data Providers Test Issuing CA v1', expired=False):
            now = datetime.now(timezone.utc)
            return (x509.CertificateBuilder()
                    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, customer)]))
                    .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(days=2))
                    .not_valid_after(now + timedelta(days=-1 if expired else 2))
                    .sign(self.key, hashes.SHA256()))
        pki.validate_certificate(make_cert(self.key), self.key, '0123456-7')
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for cert in [make_cert(other), make_cert(self.key, customer='7654321-0'),
                     make_cert(self.key, issuer='Production'), make_cert(self.key, expired=True)]:
            with self.assertRaises(pki.SafeError):
                pki.validate_certificate(cert, self.key, '0123456-7')


if __name__ == '__main__':
    unittest.main()
