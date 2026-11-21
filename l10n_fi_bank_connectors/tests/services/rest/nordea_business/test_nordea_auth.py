import requests

from unittest.mock import patch, MagicMock

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .....services.auth.token_cache import _token_cache
from .....services.rest.nordea_business.constants.nordea_auth_config import BACKEND_SANDBOX, BACKEND_PROD
from .....services.rest.nordea_business.nordea_auth import NordeaAuth

OAUTH_REDIRECTION_URL = "https://example.com/callback"
PATCH_SESSION = 'odoo.addons.l10n_fi_bank_connectors.services.rest.nordea_business.nordea_http.requests.Session'


def _make_conn(conn_id=1, sandbox=True, refresh_token="stored_refresh_token"):
    conn = MagicMock()
    conn.id = conn_id
    conn.name = f"Test Connection {conn_id}"
    conn.api_backend = BACKEND_SANDBOX.key if sandbox else BACKEND_PROD.key
    conn.client_id_decrypted = "test_client_id"
    conn.client_secret_decrypted = "test_client_secret"
    conn.refresh_token_decrypted = refresh_token
    conn.nordea_auth_signing_key_decrypted = None
    return conn


def _make_auth(conn=None, sandbox=True, conn_id=1):
    if conn is None:
        conn = _make_conn(conn_id=conn_id, sandbox=sandbox)
    return NordeaAuth(conn)


def _cache_key(conn):
    return (conn.api_backend, conn.id)


def _make_mock_response(access_token="test_access_token", refresh_token="new_refresh_token", expires_in=900):
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
    }
    mock_resp.status_code = 200
    return mock_resp


def _mock_session(mock_session_class, access_token="test_access_token", refresh_token="new_refresh_token", expires_in=900):
    """Configure a mock Session instance for successful token responses."""
    mock_resp = _make_mock_response(access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)
    mock_session_class.return_value.request.return_value = mock_resp
    return mock_resp


class TestNordeaBusinessAuthExchangeCode(TransactionCase):

    def setUp(self):
        super().setUp()
        _token_cache.clear()

    def test_empty_auth_code_raises_user_error(self):
        """Exchanging with an empty code fails."""
        auth = _make_auth()
        with self.assertRaises(UserError):
            auth.exchange_auth_code("", OAUTH_REDIRECTION_URL)

    def test_empty_redirect_uri_raises_user_error(self):
        """Exchanging without a redirect URI fails."""
        auth = _make_auth()
        with self.assertRaises(UserError):
            auth.exchange_auth_code("valid_code", "")

    @patch(PATCH_SESSION)
    def test_exchange_stores_access_token_and_returns_data(self, mock_session):
        """A successful exchange caches the returned access token and returns the data."""
        _mock_session(mock_session, access_token="exchanged_token", refresh_token="new_refresh")
        conn = _make_conn()
        auth = NordeaAuth(conn)

        result = auth.exchange_auth_code("auth_code", OAUTH_REDIRECTION_URL)

        self.assertEqual(result["access_token"], "exchanged_token")
        self.assertIn(_cache_key(conn), _token_cache)
        self.assertEqual(_token_cache[_cache_key(conn)]["token"], "exchanged_token")


class TestNordeaBusinessAuthExecuteRequest(TransactionCase):
    """Successful POST requests should return the response object."""
    @patch(PATCH_SESSION)
    def test_successful_request_returns_response(self, mock_session):
        _mock_session(mock_session)
        auth = _make_auth()
        encoded_body = "grant_type=refresh_token"
        headers = auth._build_token_request_headers(encoded_body, encoded_body)

        response = auth._execute_token_request(encoded_body, headers)

        self.assertEqual(response.status_code, 200)
