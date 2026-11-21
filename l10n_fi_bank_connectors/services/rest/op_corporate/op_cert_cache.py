from ...auth.cert_cache import get_or_create_cert_files as _get_or_create, invalidate_cert_cache as _invalidate
from .constants.op_auth_config import PROVIDER_NAME


def get_or_create_cert_files(cache_key: tuple, cert_pem: str, key_pem: str) -> tuple[str, str]:
    """Return cached OP mTLS cert files, write new temp files only if cert has changed."""
    return _get_or_create(PROVIDER_NAME, cache_key, cert_pem, key_pem)


def invalidate_cert_cache(cache_key: tuple):
    """Remove cached OP mTLS cert files and delete them from disk."""
    _invalidate(PROVIDER_NAME, cache_key)