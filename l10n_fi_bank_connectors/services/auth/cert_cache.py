import hashlib
import logging
import os
import tempfile
import threading

_logger = logging.getLogger(__name__)

_cert_cache: dict[tuple, dict] = {}
_cert_cache_lock = threading.Lock()

"""Certificate cache methods used by various providers"""

def _compute_pems_digest(*pems: str) -> str:
    """Compute a SHA-256 hash over PEM strings."""
    h = hashlib.sha256()
    for pem in pems:
        h.update(pem.encode())
    return h.hexdigest()

def _write_pem_file(pem: str) -> str:
    """Write a PEM string to a temporary file and return its path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False)
    try:
        with f:
            f.write(pem)
    except BaseException:
        os.unlink(f.name)
        raise
    return f.name

def _write_cert_files(cert_pem: str, key_pem: str) -> tuple[str, str]:
    """Write cert and key to temp files. Either both exist afterwards, or neither."""
    cert_path = _write_pem_file(cert_pem)
    try:
        key_path = _write_pem_file(key_pem)
    except BaseException:
        os.unlink(cert_path)
        raise
    return cert_path, key_path


def _cleanup_cert_files(cert_path: str, key_path: str):
    for path in (cert_path, key_path):
        try:
            os.unlink(path)
        except OSError:
            pass

def get_or_create_cert_files(provider: str, cache_key: tuple, cert_pem: str, key_pem: str) -> tuple[str, str]:
    """Return cached, write new temp files only if cert has changed."""
    if not cert_pem:
        raise ValueError("cert_pem must not be empty")
    if not key_pem:
        raise ValueError("key_pem must not be empty")
    namespaced_key = (provider, *cache_key)
    cert_hash = _compute_pems_digest(cert_pem, key_pem)

    # return cached
    with _cert_cache_lock:
        entry = _cert_cache.get(namespaced_key)
        if entry and entry["hash"] == cert_hash:
            return entry["cert_path"], entry["key_path"]

    # write new
    cert_path, key_path = _write_cert_files(cert_pem, key_pem)

    with _cert_cache_lock:
        entry = _cert_cache.get(namespaced_key)
        if entry and entry["hash"] == cert_hash:
            _cleanup_cert_files(cert_path, key_path)
            return entry["cert_path"], entry["key_path"]
        if entry:
            _cleanup_cert_files(entry["cert_path"], entry["key_path"])
        _cert_cache[namespaced_key] = {
            "cert_path": cert_path,
            "key_path": key_path,
            "hash": cert_hash,
        }

    _logger.debug("%s: cert files written for cache_key=%s", provider, cache_key)
    return cert_path, key_path

def invalidate_cert_cache(provider: str, cache_key: tuple):
    """Remove cached cert files and delete them from disk. Namespaced by provider."""
    namespaced_key = (provider, *cache_key)
    with _cert_cache_lock:
        entry = _cert_cache.pop(namespaced_key, None)
        if entry:
            _cleanup_cert_files(entry["cert_path"], entry["key_path"])
