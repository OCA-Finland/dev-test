import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.auth.token_cache import invalidate_token_cache
from ..services.constants.backend_schedules import next_daily_run, schedule_for_family
from ..services.constants.connection import ConnectionStatus
from ..services.rest.op_corporate.op_cert_cache import invalidate_cert_cache as invalidate_op_cert_cache
from ..services.service_factory import _REGISTRY, get_visible_backends
from ..services.soap.nordea_corporate_access.nordea_ca_cert_cache import invalidate_cert_cache as invalidate_nca_cert_cache


_logger = logging.getLogger(__name__)


def _default_api_backend(self):
    """First visible sandbox backend if any, else the first visible backend."""
    visible = get_visible_backends()
    return next(
        (b.key for b in visible if b.sandbox),
        next((b.key for b in visible), None),
    )


class OnlineBankingConnection(models.Model):
    _name = 'online.banking.connection'
    _description = "Online Banking Connection"
    _rec_name = 'name'

    name = fields.Char("Name", required=True)

    api_backend = fields.Selection(
        selection=lambda self: [b.as_choice() for b in get_visible_backends()],
        string="API Backend",
        required=True,
        default=_default_api_backend,
    )

    company_id = fields.Many2one(
        'res.company',
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    status = fields.Selection(
        selection=ConnectionStatus.SELECTION,
        string="Status",
        required=True,
        default='pending',
    )

    last_auth_attempt = fields.Datetime(
        string="Last Auth Attempt",
        readonly=True,
        copy=False,
    )

    bank_account_ids = fields.One2many(
        'online.banking.account',
        'connection_id',
        string="Bank Accounts",
    )

    bank_account_count = fields.Integer(
        string="Account Count",
        compute="_compute_bank_account_count",
    )

    credential_ids = fields.One2many(
        comodel_name='online.banking.credential',
        inverse_name='connection_id',
        string='Credentials',
    )

    account_info_last_synced_at = fields.Datetime(
        string="Account Info Last Synced",
        readonly=True,
        copy=False,
        help="When account information was last successfully fetched and synced.",
    )

    account_info_next_run = fields.Datetime(
        string="Account Info Next Run",
        readonly=True,
        copy=False,
        help="When the scheduled account information refresh is next due.",
    )

    account_info_schedule_signature = fields.Char(
        readonly=True,
        copy=False,
    )

    # helper to show/hide backend-specific fields
    backend_family = fields.Selection(
        selection=lambda self: list({
            (b.family, b.family.replace('_', ' ').title())
            for b in _REGISTRY.values()
            if b.family
        }),
        string="Backend Family",
        compute="_compute_backend_family",
        store=False,
    )

    @api.depends('api_backend')
    def _compute_backend_family(self):
        for rec in self:
            backend = _REGISTRY.get(rec.api_backend)
            rec.backend_family = backend.family if backend else False

    @api.depends('bank_account_ids')
    def _compute_bank_account_count(self):
        for rec in self:
            rec.bank_account_count = len(rec.bank_account_ids)

    def _process_account_dtos(self, account_dtos):
        """Upsert bank accounts from a list of account DTOs."""
        imported_count = 0
        updated_count = 0
        Account = self.env['online.banking.account']
        
        currency_map = self._validate_account_dto_currency(account_dtos)

        with self.env.cr.savepoint():
            for dto in account_dtos:
                vals = {
                    'connection_id': self.id,
                    **self._prepare_account_vals(dto, currency_map),
                }
                existing = Account.search([
                    ('connection_id', '=', self.id),
                    ('external_account_id',  '=', dto.external_id),
                ], limit=1)

                if existing:
                    existing.write(vals)
                    updated_count += 1
                else:
                    Account.create(vals)
                    imported_count += 1

        return imported_count, updated_count
    
    def _validate_account_dto_currency(self, account_dtos):
        """
        Validates that every currency code referenced by the incoming DTOs is active in Odoo. 
        If any are missing, raises a UserError listing all unknown codes and instructing the user to activate them via Settings → Currencies.
        """
        required_codes = {dto.currency for dto in account_dtos if dto.currency}
        if required_codes:
            found_currencies = self.env['res.currency'].with_context(active_test=False).search([
                ('name', 'in', list(required_codes))
            ])
            found_codes = {c.name for c in found_currencies}
            missing_codes = sorted(required_codes - found_codes)
            if missing_codes:
                raise UserError(_(
                "The following currencies are not available in Odoo and must be "
                "activated before importing: %(currencies)s.\n"
                "To activate them, go to Settings → Currencies.",
                currencies=", ".join(missing_codes),
            ))
            return {c.name: c for c in found_currencies}
        else:
            return {}

    def _prepare_account_vals(self, dto, currency_map):
        """Prepare data for the online_banking_account table."""
        currency = currency_map.get(dto.currency)
        return {
            'external_account_id': dto.external_id,
            'iban': dto.iban,
            'bic': dto.bic,
            'name': dto.name,
            'balance': float(dto.balance) if dto.balance is not None else 0.0,
            'currency_id': currency.id if currency else None,
            'raw_data': json.dumps(dto.raw) if dto.raw else "",
            'product': dto.product,
        }
    
    def _resume_providers_after_auth(self):
        """Resume all providers paused due to an auth error on this connection."""
        self.ensure_one()
        providers = self.env['online.bank.statement.provider'].search([
            ('cron_paused', '=', True),
            ('cron_pause_reason', '=', 'auth_error'),
            ('connection_id', '=', self.id),
        ])
        if not providers:
            return
        
        for provider in providers:
            paused_since = provider._resume_provider()
            provider.message_post(
                body=_(
                    "Scheduled pull has been re-enabled after successful "
                    "re-authorization. Transactions since %(since)s will be "
                    "fetched on the next scheduled run.",
                    since=paused_since or _("unknown"),
                )
            )
            _logger.info(
                "Provider '%s' cron resumed after re-authorization. "
                "next_run set to %s.",
                provider.name, paused_since,
            )
        _logger.info(
            "Provider '%s' cron resumed after re-authorization. "
            "next_run set to %s.",
            provider.name, paused_since,
        )

    @api.ondelete(at_uninstall=False)
    def _unlink_if_statement_providers_exist(self):
        providers = self.env['online.bank.statement.provider'].search(
            [('connection_id', 'in', self.ids)],
            limit=1,
        )
        if providers:
            raise UserError(_("You cannot delete a connection that is used by a statement provider. Remove or reassign the provider first."))

    def write(self, vals):
        """
        Handles backend change and behavior on pending -> active status change
        - only pending connections can change backend
        - clear credentials and caches on a backend change
        - when a connection becomes active, sets the account info schedule
        """
        changed_backend = self._get_changed_backend_connections(vals)
        self._check_backend_change_allowed(changed_backend)
        self._check_status_change_allowed(vals)

        old_backends = {
            connection.id: connection.api_backend
            for connection in changed_backend
        }
        newly_active = self._get_newly_active_connections(vals)

        result = super().write(vals)

        if changed_backend:
            changed_backend._clear_credentials_and_caches(old_backends, vals['api_backend'])

        newly_active._sync_account_info_schedule()

        return result

    def _sync_account_info_schedule(self):
        for connection in self:
            schedule = schedule_for_family(connection.backend_family)
            if schedule is None:
                _logger.warning(
                    "No backend schedule for family %r (connection %s); skipping account info schedule sync.",
                    connection.backend_family, connection.id,
                )
                continue

            signature = f"{schedule.run_hour}|{schedule.run_minute}|{schedule.tz_name}"
            if connection.account_info_schedule_signature == signature:
                continue

            base = connection.account_info_last_synced_at or fields.Datetime.now()
            super(OnlineBankingConnection, connection).write({
                "account_info_schedule_signature": signature,
                "account_info_next_run": next_daily_run(schedule, base),
            })

    def _get_newly_active_connections(self, vals):
        if vals.get('status') != ConnectionStatus.ACTIVE:
            return self.browse()
        return self.filtered(
            lambda connection: connection.status != ConnectionStatus.ACTIVE
        )

    def _get_changed_backend_connections(self, vals):
        if 'api_backend' not in vals:
            return self.browse()
        return self.filtered(
            lambda connection: connection.api_backend != vals['api_backend']
        )

    def _check_backend_change_allowed(self, changed_backend):
        protected = changed_backend.filtered(
            lambda connection: connection.status in (
                ConnectionStatus.ACTIVE,
                ConnectionStatus.EXPIRED,
            )
        )
        if protected:
            raise UserError(_("You cannot change the API backend of an active or expired connection."))

    def _check_status_change_allowed(self, vals):
        if vals.get('status') != ConnectionStatus.PENDING:
            return

        protected = self.filtered(
            lambda connection: connection.status in (
                ConnectionStatus.ACTIVE,
                ConnectionStatus.EXPIRED,
            )
        )
        if protected:
            raise UserError(_("An active or expired connection cannot be reset to Pending."))


    def _clear_credentials_and_caches(self, old_backends, new_backend):
        self.env['online.banking.credential'].sudo().search([
            ('connection_id', 'in', self.ids),
        ]).unlink()

        for connection in self:
            cache_keys = {
                (old_backends[connection.id], connection.id),
                (new_backend, connection.id),
            }
            for key in cache_keys:
                invalidate_token_cache(key)
                invalidate_op_cert_cache(key)
                invalidate_nca_cert_cache(key)