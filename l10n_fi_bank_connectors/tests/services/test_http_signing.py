import os

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import timedelta, datetime,timezone
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from ...services.constants.connection import CONFIG_KEY
from ...services.constants.crypto import RSA_SHA256
from ...utils.crypto import (
    encrypt_fernet, 
    decrypt_fernet, 
    parse_cert_expiry,
    load_rsa_private_key,
    )
from ...utils.rest.http_signing import build_http_signature
    


def _make_key() -> str:
    return Fernet.generate_key().decode()

def _patched_key(key):
    return patch("odoo.addons.l10n_fi_bank_connectors.utils.crypto.config", **{"get.return_value": key})

def _make_self_signed_cert_pem(days_valid=365) -> str:
    """Generate a minimal self-signed RSA certificate for testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"test"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=days_valid))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()

def _make_rsa_private_key_pem() -> str:
    """Generate an RSA private key in PEM format for testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

class TestHttpSigning(TransactionCase):
    
    def test_encrypt_decrypt_with_configured_key(self):
        """Round-trip with the configured key even if the environment key is invalid."""
        key = _make_key()
        with _patched_key(key), patch.dict(
            os.environ, {"ODOO_BANKING_ENCRYPTION_KEY": "invalid"}
        ):
            ciphertext = encrypt_fernet("super-secret")
            result = decrypt_fernet(ciphertext)
        self.assertEqual(result, "super-secret")

    def test_key_falls_back_to_environment(self):
        key = _make_key()
        with _patched_key(None), patch.dict(os.environ, {"ODOO_BANKING_ENCRYPTION_KEY": key}):
            ciphertext = encrypt_fernet("secret")
        self.assertEqual(Fernet(key.encode()).decrypt(ciphertext.encode()), b"secret")

    def test_invalid_key_raises_error(self):
        """Decrypting with an invalid key raises an error."""
        key_a, key_b = _make_key(), _make_key()
        with _patched_key(key_a):
            ciphertext = encrypt_fernet("secret")
        with _patched_key(key_b):
            with self.assertRaises(InvalidToken):
                decrypt_fernet(ciphertext)
                
    def test_missing_key_raises_error(self):
        """Missing key in both sources raises an error."""
        with _patched_key(None), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                encrypt_fernet("secret")
        self.assertIn(CONFIG_KEY, str(ctx.exception))
        
class TestParseCertExpiry(TransactionCase):
        
    def test_returns_expiry_date_valid_cert(self):
        """Returns expiry date"""
        pem = _make_self_signed_cert_pem(days_valid=365)
        result = parse_cert_expiry(pem)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, datetime)
        self.assertIsNotNone(result.tzinfo)
        
    def test_returns_none_for_empty_string(self):
        """Tests empty string"""
        result = parse_cert_expiry("")
        self.assertIsNone(result)
        
class TestLoadRsaPrivateKey(TransactionCase):

    def test_loads_valid_pem_key(self):
        """Loads a valid PEM RSA private key without error."""
        pem = _make_rsa_private_key_pem()
        key = load_rsa_private_key(pem)
        self.assertIsNotNone(key)

    def test_loaded_key_has_correct_size(self):
        """Loaded key has the expected bit size."""
        pem = _make_rsa_private_key_pem()
        key = load_rsa_private_key(pem)
        self.assertEqual(key.key_size, 2048)

    def test_invalid_pem_raises_value_error(self):
        """Passing garbage raises ValueError with a descriptive message."""
        with self.assertRaises(ValueError) as ctx:
            load_rsa_private_key("not-a-key")
        self.assertIn("RSA private key", str(ctx.exception))
        
class TestBuildHttpSignature(TransactionCase):

    def _make_private_key(self):
        pem = _make_rsa_private_key_pem()
        return load_rsa_private_key(pem)

    def test_returns_string(self):
        """build_http_signature returns a string."""
        key = self._make_private_key()
        result = build_http_signature(key, "my-key-id", "POST", "/v1/payments", {})
        self.assertIsInstance(result, str)

    def test_contains_required_fields(self):
        """Output contains keyId, algorithm, headers, and signature fields."""
        key = self._make_private_key()
        result = build_http_signature(key, "key-123", "GET", "/v1/accounts", {})
        self.assertIn('keyId="key-123"', result)
        self.assertIn(f'algorithm="{RSA_SHA256}"', result)
        self.assertIn('headers=', result)
        self.assertIn('signature=', result)
