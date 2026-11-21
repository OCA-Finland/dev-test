from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from datetime import datetime, timedelta, timezone


def patch_factory(mock_factory, mock_service):
    """Configure mock_factory.from_record_ctx to work as a context manager."""
    mock_factory.from_record_ctx.return_value.__enter__.return_value = mock_service
    mock_factory.from_record_ctx.return_value.__exit__.return_value = False
    
def make_connection(env, **overrides):
    """Create a test online.banking.connection with OP sandbox defaults."""
    vals = {'name': 'Test Connection', 'api_backend': 'op_corporate_sandbox'}
    vals.update(overrides)
    return env['online.banking.connection'].create(vals)

def generate_self_signed_keypair(days_valid=1):
    """Generate an RSA key + self-signed cert pair for signing tests."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Test Nordea CA Cert"),
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
    private_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return private_key_pem, cert_pem