import logging

from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from datetime import datetime, timezone

from ..services.constants.connection import CONFIG_KEY

from odoo.tools import config

_logger = logging.getLogger(__name__)


# fernet
def _get_fernet() -> Fernet:
    """Retrieve the Fernet cipher instance from Odoo config."""
    raw = config.get(CONFIG_KEY)
    if not raw:
        raise ValueError(f"Missing '{CONFIG_KEY}'.")
    try:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception as e:
        raise ValueError(f"Invalid '{CONFIG_KEY}': {e}") from e


def encrypt_fernet(value: str) -> str:
    """Encrypt a non-empty string value using the configured Fernet key."""
    if not value:
        raise ValueError("Cannot encrypt an empty value.")
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_fernet(value: str) -> str:
    """Decrypt a non-empty encrypted string value using the configured Fernet key."""
    if not value:
        raise ValueError("Cannot decrypt an empty value.")
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        _logger.error("Decrypt failed (%s): invalid token or key.", CONFIG_KEY)
        raise


# certificate operations
def parse_cert_expiry(pem: str) -> datetime | None:
    """Parse an X.509 certificate PEM string and return its expiration datetime in UTC."""
    try:
        cert = x509.load_pem_x509_certificate(pem.encode())
        if hasattr(cert, "not_valid_after_utc"):
            return cert.not_valid_after_utc
        return cert.not_valid_after.replace(tzinfo=timezone.utc)
    except Exception as e:
        _logger.warning("Could not parse certificate expiry: %s", e)
        return None


def load_x509_certificate(pem: str) -> x509.Certificate:
    """Load an X.509 certificate from a PEM-encoded string."""
    try:
        return x509.load_pem_x509_certificate(
            pem.encode() if isinstance(pem, str) else pem,
        )
    except Exception as e:
        _logger.error("Failed to load X.509 certificate: %s", e)
        raise ValueError(
            "Failed to load certificate. Ensure it is a valid PEM-encoded X.509 certificate."
        ) from e


# key operations
def load_rsa_private_key(pem: str) -> RSAPrivateKey:
    """Load an RSA private key from a PEM-encoded string."""
    try:
        return serialization.load_pem_private_key(
            pem.encode() if isinstance(pem, str) else pem,
            password=None,
        )
    except Exception as e:
        _logger.error("Failed to load RSA private key: %s", e)
        raise ValueError(
            "Failed to load RSA private key. Ensure the key is a valid PEM-encoded RSA private key."
            ) from e


def rsa_sign(private_key: RSAPrivateKey, data: bytes) -> bytes:
    """Sign data using RSASSA-PKCS1-v1_5 with SHA-256 (RS256)."""
    try:
        return private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    except Exception as e:
        _logger.error("Failed to sign data: %s", e)
        raise TypeError(
            "Failed to sign data. "
            "Ensure the key is an RSA private key (not EC or other type)."
        ) from e
