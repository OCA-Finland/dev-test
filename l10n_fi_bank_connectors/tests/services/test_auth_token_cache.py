import time
import unittest

from unittest.mock import MagicMock

from odoo.tests.common import BaseCase

from ...services.auth.token_cache import (
    cache_token,
    get_valid_token,
    _token_cache,
    _token_cache_lock,
)

EXPIRES_IN = 3600
EXPIRES_IN_ALTERNATIVE = 1800
TOKEN_EXPIRY_BUFFER_SECONDS = 30

def _clear_cache():
    with _token_cache_lock:
        _token_cache.clear()

def _create_key(id):
    return ("nordea_business_sandbox", id)
        
class TestTokenCache(BaseCase):
    def setUp(self):
        _clear_cache()
 
    def test_stores_token_and_expiry(self):
        key = _create_key(310)
        cache_token(key, "tok123", EXPIRES_IN)
 
        with _token_cache_lock:
            entry = _token_cache[key]
 
        self.assertEqual(entry["token"], "tok123")
        self.assertAlmostEqual(entry["expiry"], time.time() + EXPIRES_IN, delta=2)
        
    def test_overwrites_existing_token(self):
        key = _create_key(310)
        cache_token(key, "old_token", EXPIRES_IN)
        cache_token(key, "new_token", EXPIRES_IN_ALTERNATIVE)
 
        with _token_cache_lock:
            entry = _token_cache[key]
 
        self.assertEqual(entry["token"], "new_token")
        self.assertAlmostEqual(entry["expiry"], time.time() + EXPIRES_IN_ALTERNATIVE, delta=2)
        
    def test_different_keys_stored_independently(self):
        key1 = _create_key(310)
        key2 = _create_key(334)
        cache_token(key1, "token_a", EXPIRES_IN)
        cache_token(key2, "token_b", EXPIRES_IN)
 
        with _token_cache_lock:
            self.assertEqual(_token_cache[key1]["token"], "token_a")
            self.assertEqual(_token_cache[key2]["token"], "token_b")


class TestGetValidToken(unittest.TestCase):
    def setUp(self):
        _clear_cache()
 
    def test_returns_cached_token_when_valid(self):
        key = _create_key(310)
        cache_token(key, "valid_token", EXPIRES_IN)
 
        fetch_fn = MagicMock(return_value="fresh_token")
        result = get_valid_token(key, fetch_fn)
 
        self.assertEqual(result, "valid_token")
        fetch_fn.assert_not_called()
 
    def test_fetch_fn_when_cache_empty(self):
        key = _create_key(310)
        fetch_fn = MagicMock(return_value="fetched_token")
 
        result = get_valid_token(key, fetch_fn)
 
        self.assertEqual(result, "fetched_token")
        fetch_fn.assert_called_once()
 
    def test_fetch_fn_when_token_expired(self):
        key = _create_key(310)
        with _token_cache_lock:
            _token_cache[key] = {"token": "old_token", "expiry": time.time() - 1}
 
        fetch_fn = MagicMock(return_value="refreshed_token")
        result = get_valid_token(key, fetch_fn)
 
        self.assertEqual(result, "refreshed_token")
        fetch_fn.assert_called_once()

    def test_fetch_fn_within_expiry_buffer(self):
        key = _create_key(310)
        
        with _token_cache_lock:
            _token_cache[key] = {
                "token": "nearly_expired",
                "expiry": time.time() + TOKEN_EXPIRY_BUFFER_SECONDS - 5,
            }
 
        fetch_fn = MagicMock(return_value="fresh_token")
        result = get_valid_token(key, fetch_fn)
 
        self.assertEqual(result, "fresh_token")
        fetch_fn.assert_called_once()
