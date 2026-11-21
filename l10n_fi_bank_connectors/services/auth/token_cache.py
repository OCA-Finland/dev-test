import logging
import threading

from time import time

from ..constants.connection import TOKEN_EXPIRY_BUFFER_SECONDS

_logger = logging.getLogger(__name__)

_token_cache: dict[tuple[str, int], dict] = {}
_token_cache_lock = threading.RLock()

def get_valid_token(cache_key: tuple, fetch_fn) -> str:
    """Return a cached token if still valid, otherwise call fetch_fn to get a new one."""
    with _token_cache_lock:
        cached = _token_cache.get(cache_key)
        if cached and time() < cached["expiry"] - TOKEN_EXPIRY_BUFFER_SECONDS:
            _logger.info("Reusing the cached token.")
            return cached["token"]
        return fetch_fn()

def cache_token(cache_key: tuple, token: str, expires_in: int):
    """Store a token in the cache."""
    with _token_cache_lock:
        _token_cache[cache_key] = {
            "token": token,
            "expiry": time() + expires_in,
        }

def invalidate_token_cache(cache_key: tuple):
    """Remove cached token for the given cache key."""
    with _token_cache_lock:
        _logger.info("Removing the cached token.")
        _token_cache.pop(cache_key, None)
    _logger.debug("Token cache invalidated for cache_key=%s", cache_key)
    