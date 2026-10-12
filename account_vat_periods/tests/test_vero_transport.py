"""Real loopback TLS: no Tax Administration calls or real credentials."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import ssl
import tempfile
from threading import Thread
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import requests
from odoo.tests import TransactionCase, tagged

from ..vero_transport import MemoryCertificate


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass


@tagged('post_install', '-at_install', 'vero_transport')
class TestVeroTransport(TransactionCase):
    def test_memory_mutual_tls_and_server_verification(self):
        now = datetime.now(timezone.utc)
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'TLS fixture CA')])

        def issue(name, key, ca=False):
            builder = x509.CertificateBuilder().subject_name(x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, name)])).issuer_name(ca_name)
            builder = builder.public_key(key.public_key()).serial_number(x509.random_serial_number())
            builder = builder.not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            builder = builder.add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
            if not ca:
                builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
                builder = builder.add_extension(x509.ExtendedKeyUsage([
                    ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            return builder.sign(ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)

        def pem(key):
            return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

        ca = issue('TLS fixture CA', ca_key, ca=True)
        server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        client = MemoryCertificate(issue('client', client_key), pem(client_key))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'ca.pem').write_bytes(ca)
            (root / 'server.pem').write_bytes(issue('localhost', server_key))
            (root / 'server-key.pem').write_bytes(pem(server_key))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(root / 'server.pem', root / 'server-key.pem')
            context.load_verify_locations(root / 'ca.pem')
            context.verify_mode = ssl.CERT_REQUIRED
            server = HTTPServer(('127.0.0.1', 0), Handler)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = 'https://localhost:%s/' % server.server_port
                # Without our fixture CA the server certificate must be rejected.
                with self.assertRaises(requests.exceptions.SSLError):
                    client.post(url, timeout=3)
                with patch('certifi.where', return_value=str(root / 'ca.pem')):
                    with patch('tempfile.mkstemp', side_effect=AssertionError('Client TLS must not create files')):
                        self.assertEqual(client.post(url, timeout=3).json(), {'ok': True})
                    with self.assertRaises(requests.exceptions.SSLError):
                        client.post(url.replace('localhost', '127.0.0.1'), timeout=3)
                with requests.Session() as session:
                    session.trust_env = False
                    with self.assertRaises(requests.exceptions.SSLError):
                        session.post(url, verify=str(root / 'ca.pem'), timeout=3)
                self.assertEqual({p.name for p in root.iterdir()}, {'ca.pem', 'server.pem', 'server-key.pem'})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
