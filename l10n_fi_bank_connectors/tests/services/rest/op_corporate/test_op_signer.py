import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from odoo.tests.common import TransactionCase

from .....services.rest.op_corporate.op_payment_signer import sign_request

def _generate_rsa_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048,)
    
def _key_to_pem(private_key: RSAPrivateKey) -> str:
    """Serialize an RSA private key to PEM string."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

def _parse_jws(token: str) -> tuple[dict, str]:
    """Parse a detached JWS token into {encoded_header}..{encoded_signature}"""
    parts = token.split('..')
    assert len(parts) == 2, f"Expected exactly one '..' in token, got: {token}"
    encoded_header, encoded_signature = parts

    padding_needed = 4 - len(encoded_header) % 4
    padded = encoded_header + ('=' * (padding_needed % 4))
    header = json.loads(base64.urlsafe_b64decode(padded))

    return header, encoded_header, encoded_signature

class TestOPSigner(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._private_key = _generate_rsa_key()
        cls._private_key_pem = _key_to_pem(cls._private_key)
        cls._public_key = cls._private_key.public_key()
        cls._kid = "test-kid-001"
        
    def test_output_has_detached_format(self):
        """Output must be {header}..{signature} with empty payload position."""
        token = sign_request('{"amount":"1.00"}', self._private_key_pem, self._kid)
        self.assertIn('..', token)
        parts = token.split('..')
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0])
        self.assertTrue(parts[1])
        
    def test_payload_not_in_output(self):
        """The payload must not appear anywhere in the output token."""
        payload = '{"creditorIban":"FI42"}'
        token = sign_request(payload, self._private_key_pem, self._kid)
        self.assertNotIn('creditorIban', token)
        self.assertNotIn('FI42', token)
        
    def test_header_contains_required_fields(self):
        """JWS header must contain alg, kid, b64, urn:op.api.iat, crit."""
        token = sign_request('{"amount":"1.00"}', self._private_key_pem, self._kid)
        header, _, _ = _parse_jws(token)

        self.assertEqual(header['alg'], 'RS256')
        self.assertEqual(header['kid'], self._kid)
        self.assertFalse(header['b64'])
        self.assertIn('urn:op.api.iat', header)
        self.assertIn('crit', header)
        self.assertIn('b64', header['crit'])
        self.assertIn('urn:op.api.iat', header['crit'])

    def test_header_is_compact_json(self):
        """Header JSON must have no extra whitespace."""
        token = sign_request('{"amount":"1.00"}', self._private_key_pem, self._kid)
        _, encoded_header, _ = _parse_jws(token)

        padding_needed = 4 - len(encoded_header) % 4
        padded = encoded_header + ('=' * (padding_needed % 4))
        raw_header = base64.urlsafe_b64decode(padded).decode()

        self.assertNotIn(' ', raw_header)
        
    def test_signature_is_valid(self):
        """
        The signature must be verifiable using the corresponding public key.
        Reconstructs the signing input and verifies with PKCS1v15/SHA256.
        """
        payload = '{"amount":"1.00","currency":"EUR"}'
        token = sign_request(payload, self._private_key_pem, self._kid)
        _, encoded_header, encoded_signature = _parse_jws(token)

        signing_input = f"{encoded_header}.".encode() + payload.encode('utf-8')

        padding_needed = 4 - len(encoded_signature) % 4
        padded_sig = encoded_signature + ('=' * (padding_needed % 4))
        signature_bytes = base64.urlsafe_b64decode(padded_sig)

        try:
            self._public_key.verify(
                signature_bytes,
                signing_input,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except Exception as e:
            self.fail(f"Signature verification failed: {e}")

    def test_empty_payload_raises_value_error(self):
        """Empty payload must raise ValueError."""
        with self.assertRaises(ValueError):
            sign_request('', self._private_key_pem, self._kid)

    def test_empty_key_raises_value_error(self):
        """Empty signing key must raise ValueError."""
        with self.assertRaises(ValueError):
            sign_request('{"amount":"1.00"}', '', self._kid)

    def test_empty_kid_raises_value_error(self):
        """Empty kid must raise ValueError."""
        with self.assertRaises(ValueError):
            sign_request('{"amount":"1.00"}', self._private_key_pem, '')

    def test_wrong_key_type_raises_type_error(self):
        """A non-RSA key (e.g. EC) must raise TypeError."""
        ec_key = ec.generate_private_key(ec.SECP256R1())
        ec_pem = ec_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        with self.assertRaises(TypeError):
            sign_request('{"amount":"1.00"}', ec_pem, self._kid)