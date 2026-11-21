import logging
import requests
import urllib.parse

from datetime import timedelta
from email.utils import formatdate

from odoo import fields, _
from odoo.exceptions import UserError

from ..base_auth import BaseAuth
from ...constants.credentials import CredentialType
from ...constants.http import (
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_FORM,
    ENCODING_UTF8,
    HEADER_CONTENT_TYPE,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    BEARER_PREFIX,
    )
from .constants.nordea_api import (
    AUTH_TOKEN_PATH,
    AUTH_TOKEN_URL,
    BASE_URL,
    HEADER_IBM_CLIENT_ID,
    HEADER_DIGEST,
    HEADER_NORDEA_DATE,
    HEADER_NORDEA_HOST,
    HEADER_NORDEA_SANDBOX_AUTHORIZER_ID,
    HEADER_IBM_CLIENT_SECRET,
    SANDBOX_SIGNATURE,
    SANDBOX_PSU_FI, 
    X_NORDEA_HOST
    )
from .constants.nordea_auth_config import (
    BACKEND_SANDBOX, 
    TOKEN_DEFAULT_EXPIRY_SECONDS, 
    MAX_CONSENT_DURATION_SANDBOX_DAYS,
    MAX_CONSENT_DURATION_PRODUCTION_DAYS
    )
from .nordea_http import NordeaHTTPClient
from ....utils.clock import to_odoo_utc_datetime, utc_now
from ....utils.crypto import load_rsa_private_key
from ....utils.rest.oauth import encode_params_alphabetically
from ....utils.rest.http_signing import build_http_signature, compute_sha256_digest

_logger = logging.getLogger(__name__)


class NordeaAuth(BaseAuth):
    def __init__(self, connection, error_handler=None):
        super().__init__(connection)
        self._client_id = connection.client_id_decrypted
        self._client_secret = connection.client_secret_decrypted
        self._sandbox = connection.api_backend == BACKEND_SANDBOX.key
        self._signing_key_pem = connection.nordea_auth_signing_key_decrypted or None
        self._error_handler = error_handler
        self.base_url = BASE_URL
        self._http_client = NordeaHTTPClient(self, self.base_url, error_handler=self._error_handler)
        
    def close(self) -> None:
        self._http_client.close()
 
    def __enter__(self) -> "NordeaAuth":
        return self
 
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        
    # public
    def build_authorize_url(self, path: str, body: dict) -> str:
        """
        POST to the /authorize endpoint via the shared http client and return
        the redirect Location URL. Used by the OAuth wizard.
        """
        return self._http_client.post_authorize(path, body)
    
    def get_auth_headers(self, method: str, path: str, body_bytes: bytes = None) -> dict:
        """Return headers required for every Nordea API call."""
        token = self.get_valid_token()
        date_str = formatdate(usegmt=True)
        headers = self._get_base_headers(
            date_str=date_str,
            method=method,
            path=path,
            body_bytes=body_bytes,
        )
        headers.update(self._build_auth_headers(token))
        return headers
    
    def get_sandbox_authorizer_header(self) -> dict:
        """Return the sandbox-only header for API calls (and an empty dict in production)."""
        if self._sandbox:
            return {HEADER_NORDEA_SANDBOX_AUTHORIZER_ID: SANDBOX_PSU_FI}
        return {}
    
    def exchange_auth_code(self, auth_code: str, redirect_uri: str) -> dict:
        """Exchange an authorization code for access + refresh tokens."""
        if not auth_code or not auth_code.strip():
            raise UserError(_("Authorization code must not be empty."))
        if not redirect_uri or not redirect_uri.strip():
            raise UserError(_("Redirect URI must not be empty."))

        clean_code = urllib.parse.unquote(auth_code.strip())
        data = self._post_token({
            'grant_type': 'authorization_code',
            'code': clean_code,
            'redirect_uri': redirect_uri.strip(),
        })
        self._store_tokens(data)
        self.connection._resume_providers_after_auth()
        return data
    
    # token fetching
    def _fetch_or_refresh_access_token(self) -> str:
        """Use the stored refresh token to obtain a new access token."""
        refresh_token = self.connection.refresh_token_decrypted
        if not refresh_token:
            raise UserError(
                _("No refresh token found for connection '%s'. "
                  "Please complete the Nordea authorization flow first.")
                % self.connection.name
            )
        _logger.info("Fetching new Nordea access token.")
        data = self._post_token({
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        })
        self._store_tokens(data)
        return data["access_token"]
    
    def _post_token(self, body: dict) -> dict:
        encoded_body = encode_params_alphabetically(body)
        normalized_body = "&".join(f"{k}={v}" for k, v in sorted(body.items()))
        headers = self._build_token_request_headers(encoded_body, normalized_body)
        response = self._execute_token_request(encoded_body, headers)
        return self._parse_token_response(response)

    def _execute_token_request(self, encoded_body: str, headers: dict) -> requests.Response:
        return self._http_client.post_form(AUTH_TOKEN_URL, encoded_body, headers)
    
    def _build_token_request_headers(self, encoded_body: str, normalized_body: str) -> dict:
        """
        Build headers for a token endpoint POST.
        Digest is computed over the normalized (decoded) body per Nordea docs,
        not the URL-encoded bytes that are actually transmitted.
        """
        date_str = formatdate(usegmt=True)
        return self._get_base_headers(
            date_str=date_str,
            method='post',
            path=AUTH_TOKEN_PATH,
            body_bytes=normalized_body.encode(ENCODING_UTF8),
            content_type=CONTENT_TYPE_FORM,
        )

    def _parse_token_response(self, response: requests.Response) -> dict:
        """Deserialise and validate the token endpoint response."""
        data = response.json()
        if "access_token" not in data:
            raise UserError(_("Nordea token response missing 'access_token'. Response: %s") % data)
        return data

    # token storage
    def _store_tokens(self, data: dict):
        """
        Persist the new refresh token to the credential table and cache
        the access token in memory.
        """
        access_token = data["access_token"]
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in", TOKEN_DEFAULT_EXPIRY_SECONDS)

        if refresh_token:
            self._write_refresh_token(refresh_token)

        self._cache_token(access_token, expires_in)

        _logger.info(
            "Nordea: access token cached for connection %s, expires in %d seconds",
            self.connection.id, expires_in,
        )
        
    def _write_refresh_token(self, refresh_token: str):
        """Upsert the refresh token credential record."""
        max_days = self._get_max_consent_duration()
        expires_at = utc_now() + timedelta(days=max_days)

        Credential = self.connection.env['online.banking.credential'].sudo()
        existing = Credential.search([
            ('connection_id', '=', self.connection.id),
            ('credential_type', '=', CredentialType.REFRESH_TOKEN),
        ], limit=1)

        if existing:
            cred = existing
        else:
            cred = Credential.create({
                'connection_id': self.connection.id,
                'credential_type': CredentialType.REFRESH_TOKEN,
                'value_encrypted': 'placeholder',
            })
        cred.set_value(refresh_token)
        cred.expires_at = fields.Datetime.to_string(
            to_odoo_utc_datetime(expires_at)
        )

        self.connection.invalidate_recordset(['credential_ids'])
        
    def _get_max_consent_duration(self) -> int:
        """Return the maximum consent duration in days based on the backend (sandbox or production)."""
        return (
            MAX_CONSENT_DURATION_SANDBOX_DAYS 
            if self._sandbox 
            else MAX_CONSENT_DURATION_PRODUCTION_DAYS
        )
    
    # headers
    def _build_auth_headers(self, token: str) -> dict:
        return {
            HEADER_AUTHORIZATION: f'{BEARER_PREFIX}{token}',
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
        }
        
    def get_pre_auth_headers(self, method: str, path: str, body_bytes: bytes = None) -> dict:
        """
        Build headers for endpoints that don't require a bearer token,
        specifically the /authorize endpoint called before any token exists.
        """
        date_str = formatdate(usegmt=True)
        return self._get_base_headers(
            date_str=date_str,
            method=method,
            path=path,
            body_bytes=body_bytes,
        )
    
    def _get_base_headers(
        self,
        date_str: str,
        method: str,
        path: str,
        body_bytes: bytes = None,
        content_type: str = CONTENT_TYPE_JSON,
    ) -> dict:
        """
        Return common headers used in Nordea API requests.

        All Nordea endpoint requests require the following parameters:
        1. X-IBM-Client-Id
        2. X-IBM-Client-Secret
        3. Signature
        - the following headers must be included in the signature:
            a) X-Nordea-Originating-Host, X-Nordea-Originating-Date (requests without body)
            b) X-Nordea-Originating-Host, X-Nordea-Originating-Date, Content-Type, Digest (requests with body)
        - signature validation is skipped in sandbox
        4. X-Nordea-Originating-Host: domain name of the server
        5. X-Nordea-Originating-Date: RFC 7231 Full Date (GMT)
        6. Digest: SHA-256 hash of the message body (requests with body only)

        For details see https://developer.nordeaopenbanking.com/apiReference
        """
        body_headers = self._build_body_headers(body_bytes, content_type) if body_bytes else {}
        signature = self._build_signature(method, path, date_str, body_headers)

        return {
            HEADER_IBM_CLIENT_ID: self._client_id,
            HEADER_IBM_CLIENT_SECRET: self._client_secret,
            HEADER_NORDEA_DATE: date_str,
            HEADER_NORDEA_HOST: X_NORDEA_HOST,
            "Signature": signature,
            **body_headers,
        }

    def _build_body_headers(self, body_bytes: bytes, content_type: str) -> dict:
        """Return Content-Type and Digest headers for requests with a body."""
        return {
            HEADER_CONTENT_TYPE: content_type,
            HEADER_DIGEST: compute_sha256_digest(body_bytes),
        }

    def _build_signature(self, method: str, path: str, date_str: str, body_headers: dict) -> str:
        """
        Build the HTTP signature over the originating date, host, and any body headers.
        Returns the sandbox skip value if no signing key is configured.
        """
        headers_to_sign = {
            HEADER_NORDEA_HOST: X_NORDEA_HOST,
            HEADER_NORDEA_DATE: date_str,
            **body_headers,
        }

        if not self._signing_key_pem:
            if not self._sandbox:
                _logger.warning(
                    "Nordea: no signing key configured for production connection %s. "
                    "Requests will likely fail.",
                    self.connection.id,
                )
            return SANDBOX_SIGNATURE

        private_key = load_rsa_private_key(self._signing_key_pem)
        return build_http_signature(
            private_key=private_key,
            key_id=self._client_id,
            method=method,
            path=path,
            headers_to_sign=headers_to_sign,
        )
