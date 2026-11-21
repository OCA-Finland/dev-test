import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.service_factory import BankingServiceFactory, _REGISTRY
from ..utils.clock import utc_today
from ..utils.statement_provider import normalize_dates, prepare_transactions_for_statements

_logger = logging.getLogger(__name__)


class OnlineBankStatementProvider(models.Model):
    _inherit = 'online.bank.statement.provider'


    # connections
    connection_id = fields.Many2one(
        'online.banking.connection',
        string='Banking Connection',
        ondelete='restrict',
        index=True,
        copy=False,
    )

    @api.model
    def _connection_ids_by_service(self):
        backends = list(_REGISTRY)
        connections = self.env['online.banking.connection'].search([
            ('api_backend', 'in', backends),
        ])
        return {
            _REGISTRY[connection.api_backend].make_service_key(connection.id): connection.id
            for connection in connections
        }

    @api.model_create_multi
    def create(self, vals_list):
        connection_ids_by_service = self._connection_ids_by_service()
        vals_list = [vals.copy() for vals in vals_list]
        for vals in vals_list:
            if 'service' in vals:
                vals['connection_id'] = connection_ids_by_service.get(vals['service']) or False
        return super().create(vals_list)

    def write(self, vals):
        vals = vals.copy()
        if 'service' in vals:
            connection_id = self._connection_ids_by_service().get(vals['service'])
            vals['connection_id'] = connection_id or False
        return super().write(vals)

    @api.model
    def _get_available_services(self):
        """Return a list of available banking services from configured connections."""
        services = super()._get_available_services()
        connections = self.env['online.banking.connection'].search([('api_backend', 'in', list(_REGISTRY.keys()))])
        for conn in connections:
            backend = _REGISTRY[conn.api_backend]
            services.append((
                backend.make_service_key(conn.id),
                f"{conn.name} ({backend.label})",
            ))
        return services

# statements
    def _obtain_statement_data(self, date_since, date_until):
        """Fetch transactions from the bank, filter them and convert to statement lines."""
        self.ensure_one()
        connection = self._resolve_connection()
        if connection is None:
            return super()._obtain_statement_data(date_since, date_until)

        banking_account = self._resolve_bank_account(connection)
        original_date_since, statement_date_until = normalize_dates(date_since, date_until)
        request_date_until = min(statement_date_until, utc_today())
        date_since = original_date_since
        
        try:
            with BankingServiceFactory.from_record_ctx(connection) as service:
                date_since = self._enforce_minimum_lookback(service, date_since)
                date_since = self._enforce_history_limit(service, date_since)
                if date_since > request_date_until:
                    _logger.warning(
                        "Skipping fetch for %s: date_since (%s) > date_until (%s)",
                        banking_account.name, date_since, request_date_until,
                    )
                    return ([], {})
                transaction_dtos = self._fetch_transaction_dtos(service, banking_account, date_since, request_date_until)
                transaction_dtos_filtered = service.filter_transactions(
                    transaction_dtos, original_date_since, statement_date_until
                )

                statement_values = service.build_statement_values(transaction_dtos_filtered)
                statement_values = self._compute_balance_values(
                    service, banking_account, original_date_since, statement_date_until, statement_values
                )

        except UserError:
            raise
        except Exception as exc:
            _logger.exception(
                "Failed to initialize banking service for connection '%s'", connection.name
            )
            raise UserError(_("Failed to initialize banking service for connection '%s': %s") % (connection.name, str(exc))
            ) from exc

        if not transaction_dtos:
            return ([], {})

        lines = [prepare_transactions_for_statements(dto) for dto in transaction_dtos_filtered]
        

        _logger.info("Built %s statement lines for %s", len(lines), banking_account.iban)
        return lines, statement_values


    def _compute_balance_values(self, service, banking_account, original_date_since, date_until, statement_values):
        """Merge balance_end_real/balance_start into statement_values, if applicable."""
        include_balances = fields.Date.to_date(date_until) >= utc_today()
        _logger.info(
            "Provider '%s': statement day=%s, include_balances=%s",
            self.name, original_date_since, include_balances,
        )
        balance_values = service._get_balance_values(banking_account.external_account_id, include_balances)
        if not balance_values:
            if include_balances:
                _logger.info(
                    "Provider '%s': include_balances=True but no balance data returned "
                    "(check OPAIS._get_current_balance / API response)",
                    self.name,
                )
            return statement_values

        _logger.info(
            "Provider '%s': fetched balance_end_real=%s for statement day %s",
            self.name, balance_values.get('balance_end_real'), original_date_since,
        )
        previous = self.env['account.bank.statement'].search([
            ('journal_id', '=', self.journal_id.id),
            ('name', '<', self.make_statement_name(original_date_since)),
        ], order='name desc', limit=1)
        if previous.balance_end_real:
            _logger.info(
                "Provider '%s': balance_start=%s from previous statement '%s'",
                self.name, previous.balance_end_real, previous.name,
            )
            statement_values['balance_start'] = previous.balance_end_real
        else:
            _logger.info(
                "Provider '%s': no usable previous statement found before '%s' (previous=%s) "
                "— balance_start left unset, parent fallback applies",
                self.name, self.make_statement_name(original_date_since), previous.name or 'none',
            )
        statement_values.update(balance_values)
        return statement_values

    # TODO remove before production
    def _get_statement_filtered_lines(self, unfiltered_lines, statement_values, statement_date_since, statement_date_until):
        """Override the parent method to log how many transactions get discarted"""
        fetched_count = len(unfiltered_lines) if unfiltered_lines else 0
        
        if unfiltered_lines:
            incoming_ids = [l.get('unique_import_id') for l in unfiltered_lines if l.get('unique_import_id')]
            if incoming_ids:
                existing = self.env['account.bank.statement.line'].sudo().search([
                    ('unique_import_id', 'in', incoming_ids),
                ])
                existing_by_id = {l.unique_import_id: l for l in existing}
                for line in unfiltered_lines:
                    uid = line.get('unique_import_id')
                    match = existing_by_id.get(uid)
                    if match:
                        _logger.warning(
                            "Provider '%s' (journal_id=%s, company_id=%s): dropping duplicate "
                            "unique_import_id=%s (incoming date=%s amount=%s account_number=%s) "
                            "-- matches existing line id=%s: statement_id=%s (%s), "
                            "journal_id=%s (SAME_JOURNAL=%s), company_id=%s (SAME_COMPANY=%s), "
                            "move_id=%s, is_reconciled=%s, account_number=%s, "
                            "date=%s amount=%s",
                            self.name, self.journal_id.id, self.journal_id.company_id.id,
                            uid, line.get('date'), line.get('amount'), line.get('account_number'),
                            match.id,
                            match.statement_id.id or 'NULL (orphaned line)', match.statement_id.name or 'N/A',
                            match.journal_id.id, match.journal_id.id == self.journal_id.id,
                            match.statement_id.company_id.id if match.statement_id else 'N/A',
                            match.statement_id.company_id.id == self.journal_id.company_id.id if match.statement_id else False,
                            match.move_id.id or 'NULL (no move)',
                            match.is_reconciled,
                            match.account_number,
                            match.date, match.amount,
                        )

        filtered_lines = super()._get_statement_filtered_lines(
            unfiltered_lines, statement_values, statement_date_since, statement_date_until
        )
        _logger.info(
            "Provider '%s': fetched %d lines, %d kept after dedup/date filtering (period %s - %s)",
            self.name, fetched_count, len(filtered_lines),
            statement_date_since, statement_date_until,
        )
        return filtered_lines