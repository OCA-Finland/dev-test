import logging

from datetime import datetime, timedelta, timezone
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.rest.op_corporate.constants.op_auth_config import BACKEND_SANDBOX
from ..services.service_factory import BankingServiceFactory, _REGISTRY
from ..utils.clock import utc_today
from ..utils.statement_provider import normalize_dates, prepare_transactions_for_statements

_logger = logging.getLogger(__name__)


class OnlineBankStatementProvider(models.Model):
    _inherit = 'online.bank.statement.provider'

    #connections
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

                if self.env.context.get("scheduled"):
                    date_since = self._clamp_to_history_limit(service, date_since)
                else:
                    self._validate_history_limit(service, date_since)

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
                self._post_pull_stats(connection, service, original_date_since, statement_date_until)

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

    def _post_pull_stats(self, connection, service, period_from, period_until):
        """Sandbox + manual pulls only: collect this period's pull diagnostics for the final post."""
        if self.env.context.get("scheduled") or connection.api_backend != BACKEND_SANDBOX.key:
            return
        collector = self.env.context.get("pull_stats_collector")
        stats = getattr(service, "pull_stats", None)
        if collector is None or not stats:
            return
        entry = {k: v for k, v in stats.items() if k not in ("archive_ids", "object_ids")}
        entry.update(period_from=period_from, period_until=period_until)
        collector.setdefault(self.id, []).append(entry)

    def _pull(self, *args, **kwargs):
        if self.env.context.get("scheduled"):
            return super()._pull(*args, **kwargs)
        collector = {}
        try:
            return super(OnlineBankStatementProvider, self.with_context(pull_stats_collector=collector))._pull(*args, **kwargs)
        finally:
            self._post_collected_stats(collector)


    def _post_collected_stats(self, collector):
        """One chatter message per provider: header with exact values only, then a table with one row per period."""
        def ms_utc(ms):
            return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        def span(mins, maxs):
            mins = [v for v in mins if v is not None]
            maxs = [v for v in maxs if v is not None]
            return f"{min(mins)} / {max(maxs)}" if mins and maxs else "n/a"

        for provider in self.browse(list(collector)):
            entries = collector[provider.id]
            req_from = min((e["request_from"][1] for e in entries if e.get("request_from")), default="n/a")
            req_to = max((e["request_to"][1] for e in entries if e.get("request_to")), default="n/a")
            raw_min = min((e["raw_ts_min"] for e in entries if e["raw_ts_min"] is not None), default=None)
            raw_max = max((e["raw_ts_max"] for e in entries if e["raw_ts_max"] is not None), default=None)
            raw_line = (
                f"{ms_utc(raw_min)} .. {ms_utc(raw_max)} UTC"
                if raw_min is not None and raw_max is not None else "n/a"
            )
            pulled_range = span([e.get("pulled_booking_min") for e in entries], [e.get("pulled_booking_max") for e in entries])
            header = [
                ("Periods", len(entries)),
                ("Request parameters (fromTimestamp / toTimestamp)", f"{req_from} / {req_to}"),
                ("Timestamp range", raw_line),
                ("Booking_date range", pulled_range),
                ("Total kept", sum(e.get("kept", 0) for e in entries)),
            ]

            lines = Markup("")
            for e in entries:
                items = []
                #window = f"{e['request_from'][1]} → {e['request_to'][1]}" if e.get("request_from") and e.get("request_to") else "n/a"
                #if window not in ("n/a", f"{req_from} → {req_to}"):
                #    items.append(("Request window (UTC)", window))
                items.append(("archiveId missing (rows)", e["archive_missing"]))
                items.append(("objectId missing (rows)", e["object_missing"]))
                items.append(("archiveId duplicated", f"{e.get('archive_dup_ids', 0)} ids / {e.get('archive_dup_rows', 0)} rows"))
                items.append(("objectId duplicated", f"{e.get('object_dup_ids', 0)} ids / {e.get('object_dup_rows', 0)} rows"))

                lines += Markup("• <b>%s / %s</b><br/>") % (e["period_from"], e["period_until"])
                lines += Markup("").join(
                    Markup("&nbsp;&nbsp;&nbsp;&nbsp;◦ %s: %s<br/>") % (label, value) for label, value in items
                )

            body = Markup("<b>OP sandbox pull stats</b><br/>") + Markup("").join(
                Markup("• %s: <b>%s</b><br/>") % (label, value) for label, value in header
            )
            body += Markup(
                "<br/><b>Per period</b><br/>"
            ) + lines
            provider.message_post(body=body, message_type="notification", subtype_xmlid="mail.mt_note")

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