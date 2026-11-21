import os

from time import time
from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase

from .....services.auth.cert_cache import _cert_cache
from .....services.auth.token_cache import _token_cache
from .....services.rest.op_corporate.constants.op_auth_config import BACKEND_SANDBOX, BACKEND_PROD
from .....services.rest.op_corporate.op_auth import OPAuth
from .....services.rest.op_corporate.op_cert_cache import invalidate_cert_cache

def _make_conn(conn_id=1):
    conn = MagicMock()
    conn.id = conn_id
    conn.api_backend = BACKEND_SANDBOX.key
    return conn

def _make_auth(env, client_id='client1', secret='secret', conn=None):
    if conn is None:
        conn = _make_conn()
    return OPAuth(env, client_id, secret, 'cert_pem', 'key_pem', conn)

def _mock_post_response(token='test_token', expires_in=900):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {'access_token': token, 'expires_in': expires_in}
    return mock_resp

def _extract_token(headers: dict) -> str:
    return headers['Authorization'].removeprefix('Bearer ')

class TestOPCorporateAuth(TransactionCase):

    def setUp(self):
        super().setUp()
        _token_cache.clear()
        _cert_cache.clear()
        self.conn1 = _make_conn(conn_id=1)
        self.conn2 = _make_conn(conn_id=2)
        
    def tearDown(self):
        for entry in _cert_cache.values():
            for path in (entry.get('cert_path'), entry.get('key_path')):
                if path and os.path.exists(path):
                    os.unlink(path)
        _cert_cache.clear()
        super().tearDown()

    @patch('requests.post')
    def test_get_valid_token_sandbox_url(self, mock_post):
        mock_post.return_value = _mock_post_response()
        auth = _make_auth(self.env, conn=self.conn1)
        headers = auth.get_auth_headers()
        headers['Authorization'].removeprefix('Bearer ')
        self.assertIn('sandbox', mock_post.call_args.args[0])

    @patch('requests.post')
    def test_get_valid_token_cache(self, mock_post):
        mock_post.return_value = _mock_post_response(token='cached_token')
        auth = _make_auth(self.env, conn=self.conn1)
        first = _extract_token(auth.get_auth_headers())
        second = _extract_token(auth.get_auth_headers())
        self.assertEqual(first, 'cached_token')
        self.assertEqual(second, 'cached_token')
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_get_valid_token_refresh(self, mock_post):
        mock_post.return_value = _mock_post_response(token='new_token')
        cache_key = (self.conn1.api_backend, self.conn1.id)
        _token_cache[cache_key] = {'token': 'old_token', 'expiry': time() - 1}
        auth = _make_auth(self.env, conn=self.conn1)
        token = _extract_token(auth.get_auth_headers())
        self.assertEqual(token, 'new_token')
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_multiple_connections(self, mock_post):
        def side_effect(*args, **kwargs):
            client_id = kwargs.get('data', {}).get('client_id')
            token = 'token_conn1' if client_id == 'client1' else 'token_conn2'
            return _mock_post_response(token=token)

        mock_post.side_effect = side_effect
        auth1 = _make_auth(self.env, client_id='client1', conn=self.conn1)
        auth2 = _make_auth(self.env, client_id='client2', conn=self.conn2)

        self.assertEqual(_extract_token(auth1.get_auth_headers()), 'token_conn1')
        self.assertEqual(_extract_token(auth2.get_auth_headers()), 'token_conn2')
        self.assertEqual(mock_post.call_count, 2)
 
        mock_post.reset_mock()
        auth1.get_auth_headers()
        auth2.get_auth_headers()
        mock_post.assert_not_called()

    @patch('requests.post')
    def test_get_valid_token_http_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.json.return_value = {}
        mock_post.return_value = mock_resp
        auth = _make_auth(self.env, conn=self.conn1)
        with self.assertRaises(Exception):
            auth.get_auth_headers()

    @patch('requests.post')
    def test_fetch_token_cert_files(self, mock_post):
        mock_post.return_value = _mock_post_response()
        auth = _make_auth(self.env, conn=self.conn1)
        auth._fetch_or_refresh_access_token()
        cert_arg = mock_post.call_args.kwargs.get('cert')
        self.assertIsNotNone(cert_arg)
        cert_path, key_path = cert_arg
        self.assertTrue(cert_path.endswith('.pem'))
        self.assertTrue(key_path.endswith('.pem'))
        
    @patch('requests.post')
    def test_fetch_token_cert_files_are_cached(self, mock_post):
        """Cert files are reused across calls when PEM content hasn't changed."""
        mock_post.return_value = _mock_post_response()
        auth = _make_auth(self.env, conn=self.conn1)
        cert1, key1 = auth.get_cert_paths()
        cert2, key2 = auth.get_cert_paths()
        self.assertEqual(cert1, cert2)
        self.assertEqual(key1, key2)
        self.assertTrue(os.path.exists(cert1))
 
    @patch('requests.post')
    def test_fetch_token_cert_files_invalidated_on_rotation(self, mock_post):
        """After invalidation, new cert files are written."""
        mock_post.return_value = _mock_post_response()
        auth = _make_auth(self.env, conn=self.conn1)
        cert1, key1 = auth.get_cert_paths()
        invalidate_cert_cache(auth._cache_key)
        cert2, key2 = auth.get_cert_paths()
        self.assertNotEqual(cert1, cert2)
        self.assertFalse(os.path.exists(cert1))
        self.assertFalse(os.path.exists(key1))
        self.assertTrue(os.path.exists(cert2))

    def test_missing_cert_raises_value_error(self):
        auth = OPAuth(self.env, 'c', 's', '', 'key_pem', self.conn1)
        with self.assertRaises(ValueError):
            auth.get_cert_paths()

    def test_missing_key_raises_value_error(self):
        auth = OPAuth(self.env, 'c', 's', 'cert_pem', '', self.conn1)
        with self.assertRaises(ValueError):
            auth.get_cert_paths()
            