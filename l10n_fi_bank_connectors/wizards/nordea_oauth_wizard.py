import logging

from datetime import datetime, timedelta, timezone

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.rest.nordea_business.nordea_auth import NordeaAuth
from ..services.constants.credentials import CredentialType
from ..services.constants.http import HTTPS_SCHEME
from ..services.rest.nordea_business.constants.nordea_api import (
    AUTH_AUTHORIZE_URL,
    EXAMPLE_REDIRECT_URI,
    SCOPE_ACCOUNTS_BASIC,
    SCOPE_ACCOUNTS_BALANCES,
    SCOPE_ACCOUNTS_DETAILS,
    SCOPE_ACCOUNTS_TRANSACTIONS,
    SCOPE_PAYMENTS_MULTIPLE
)
from ..services.rest.nordea_business.constants.nordea_auth_config import (
    BACKEND_SANDBOX,
    MAX_CONSENT_DURATION_SANDBOX_SECS,
    MAX_CONSENT_DURATION_PRODUCTION_SECS,
    PROVIDER_NAME
)
from ..services.error_handling.nordea_business_error_handler import NordeaBusinessErrorHandler
from ..utils.clock import to_odoo_utc_datetime, utc_now
from ..utils.rest.oauth import generate_state

_logger = logging.getLogger(__name__)


class NordeaOAuthWizard(models.TransientModel):
    """Wizard for handling Nordea authorization flow.
    for details see https://documentation.nordeaopenbanking.com/compliance/business/authorization-v5#overview-of-access-authorisation-api
    """
    _name = 'nordea.oauth.wizard'
    _description = 'Nordea OAuth Authorization'

    connection_id = fields.Many2one(
        comodel_name='online.banking.connection',
        required=True,
        readonly=True,
    )

    # Flow control
    state = fields.Selection(
        selection=[
            ('get_url', 'Authorization request'),
            ('exchange', 'Authorization code exchange'),
        ],
        default='get_url',
        required=True,
        readonly=True,
    )

    # Authorization request fields
    redirect_uri = fields.Char(
        string="Redirect URI",
        required=True,
        help=(
            "The redirect URI registered in the Nordea developer portal for your application. " 
            "Nordea will append ?code=<code> to this URI after the user authenticates."
        ),
    )

    scope_accounts_basic = fields.Boolean(
        string="Account List (ACCOUNTS_BASIC)",
        default=True,
    )
    
    scope_accounts_balances = fields.Boolean(
        string="Account Balances (ACCOUNTS_BALANCES)",
        default=True,
    )
    
    scope_accounts_details = fields.Boolean(
        string="Account Details (ACCOUNTS_DETAILS)",
        default=True,
    )
    
    scope_accounts_transactions = fields.Boolean(
        string="Transactions (ACCOUNTS_TRANSACTIONS)",
        default=True,
    )
    
    scope_payments_multiple = fields.Boolean(
        string="SEPA Payments (PAYMENTS_MULTIPLE)",
        default=True,
    )

    duration = fields.Integer(
        string="Consent Duration (seconds)",
        default=MAX_CONSENT_DURATION_SANDBOX_SECS,
        required=True,
        help=(
            "How long (in seconds) the consent should be valid. "
            "Sandbox maximum: 3 days. "
            "Production maximum: 180 days."
        ),
    )

    # SE, DK, NO to be implemented later
    country = fields.Selection(
        selection=[
            ('FI', 'Finland')
        ],
        string="Country",
        default="FI",
        required=True,
        help="The country of the Nordea accounts to authorize access to.",
    )

    authorize_url = fields.Char(
        string="Authorization URL",
        readonly=True,
        help="Open this URL in a browser to complete Nordea authorization.",
    )

    # Authorization code exchange fields
    auth_code = fields.Char(
        string="Authorization Code",
        help=(
            "Paste the 'code' parameter from the redirect URL here. "
            f"Example: the redirect will look like {EXAMPLE_REDIRECT_URI}?code=<CODE>&state=..."
        ),
    )

    @api.depends('connection_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f"Nordea Authorization — {rec.connection_id.name}"
                if rec.connection_id else "Nordea Authorization"
            )

    # actions
    def action_build_auth_authorize_url(self):
        """Builds url to send to Nordea's /authorize endpoint. 
        Only required parameters are included:
        - country
        - duration
        - redirect_uri
        - scope
        - state
        (for other possible parameters to include see docs https://developer.nordeaopenbanking.com/apiReference?api=Business%2520Access%2520Authorization%2520API&version=5):
        """
        self.ensure_one()
        self._validate_authorization_request()

        scopes = self._selected_scopes()
        if not scopes:
            raise UserError(_("Select at least one scope."))

        body = {
            "state": generate_state(),
            "redirect_uri": self.redirect_uri.strip(),
            "scope": scopes,
            "duration": self.duration,
            "country": self.country,
            "response_type": "code",
        }

        error_handler = self._get_error_handler()
        with NordeaAuth(self.connection_id, error_handler=error_handler) as auth:
            login_url = auth.build_authorize_url(AUTH_AUTHORIZE_URL, body)

        self.write({"authorize_url": login_url, "state": "exchange"})
        return {
            "type": "ir.actions.act_window",
            "res_model": "nordea.oauth.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_auth_token_exchange_code(self):
        """Exchange the authorization code for access + refresh tokens.
        Stores the refresh token, marks the connection active.
        """
        self.ensure_one()
        # prevent request duplication
        self._cr.execute("SELECT id FROM nordea_oauth_wizard WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset(['state'])
        if self.state != 'exchange':
            raise UserError(_("This authorization has already been completed."))
    
        self._validate_authorization_code_exchange()

        error_handler = self._get_error_handler()
        with NordeaAuth(self.connection_id, error_handler=error_handler) as auth:
            auth.exchange_auth_code(
                auth_code=self.auth_code.strip(),
                redirect_uri=self.redirect_uri.strip(),
            )

        self._update_refresh_token_expiry()

        self.connection_id._mark_active()

        _logger.info(
            "Nordea OAuth completed for connection '%s'.",
            self.connection_id.name,
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Authorization Successful"),
                "message": _(
                    "Nordea access authorized for '%(conn)s'. "
                    "The connection is now active.",
                    conn=self.connection_id.name,
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

     # validation
    def _validate_authorization_request(self):
        """Validate the authorization request parameters before sending to Nordea."""
        # redirect URI is not empty
        if not self.redirect_uri or not self.redirect_uri.strip():
            raise UserError(_("Redirect URI must not be empty."))
        
        # redirect URI uses HTTPS protocol
        if not self.redirect_uri.strip().startswith(HTTPS_SCHEME):
            raise UserError(
                _("Redirect URI must use HTTPS. Got: '%s'")
                % self.redirect_uri
            )
        
        # duration
        is_sandbox = self.connection_id.api_backend == BACKEND_SANDBOX.key
        max_duration = MAX_CONSENT_DURATION_SANDBOX_SECS if is_sandbox else MAX_CONSENT_DURATION_PRODUCTION_SECS
        if self.duration < 1 or self.duration > max_duration:
            raise UserError(
                _("Duration must be between 1 and %d seconds (%s).")
                % (max_duration, "3 days (sandbox)" if is_sandbox else "180 days")
            )

    def _validate_authorization_code_exchange(self):
        """Validate the authorization code exchange parameters."""
        if not self.auth_code or not self.auth_code.strip():
            raise UserError(_("Paste the authorization code before continuing."))
        
        if not self.redirect_uri or not self.redirect_uri.strip():
            raise UserError( _("Redirect URI is missing. Please restart the wizard."))

    # helpers
    def _update_refresh_token_expiry(self):
        """
        Set expires_at on the refresh token credential to match the
        actual consent duration requested in the /authorize call.
        """
        expires_at = utc_now() + timedelta(seconds=self.duration)
        credential = self.connection_id.credential_ids.filtered(
            lambda c: c.credential_type == CredentialType.REFRESH_TOKEN
        )
        if credential:
            credential[0].expires_at = fields.Datetime.to_string(
                to_odoo_utc_datetime(expires_at)
            )
    
    def _selected_scopes(self) -> list[str]:
        """Build a list of OAuth scopes based on user selections."""
        scopes = []
        if self.scope_accounts_basic:
            scopes.append(SCOPE_ACCOUNTS_BASIC)
        if self.scope_accounts_balances:
            scopes.append(SCOPE_ACCOUNTS_BALANCES)
        if self.scope_accounts_details:
            scopes.append(SCOPE_ACCOUNTS_DETAILS)
        if self.scope_accounts_transactions:
            scopes.append(SCOPE_ACCOUNTS_TRANSACTIONS)
        if self.scope_payments_multiple:
            scopes.append(SCOPE_PAYMENTS_MULTIPLE)
        return scopes

    def _get_error_handler(self):
       return NordeaBusinessErrorHandler(PROVIDER_NAME)
