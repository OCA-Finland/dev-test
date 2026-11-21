import logging

from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import _, models
from odoo.exceptions import UserError

from ..services.service_factory import _REGISTRY
from ..utils.clock import utc_today
from ..utils.formatting import normalize_iban

_logger = logging.getLogger(__name__)

class OnlineBankStatementProviderFetching(models.Model):
    _inherit = 'online.bank.statement.provider'
    
    def _resolve_connection(self):
        """Return this provider's banking connection, if it has one."""
        self.ensure_one()
        if not self.connection_id:
            return None

        expected_service = _REGISTRY[self.connection_id.api_backend].make_service_key(
            self.connection_id.id
        )

        if self.service != expected_service:
            raise UserError(
                _("Provider '%s' is inconsistent with its banking connection. "
                "Please reconfigure it.") % self.name
            )
        return self.connection_id
    
    def _resolve_bank_account(self, connection):
        """Resolve the banking account matching the journal's IBAN within the given connection."""
        journal_iban = self.journal_id.bank_account_id.acc_number
        if not journal_iban:
            raise UserError(_("Journal '%s' does not have a bank account number set.") % self.journal_id.name)
        banking_account = self.env['online.banking.account'].search([
            ('connection_id', '=', connection.id),
            ('iban', '=', normalize_iban(journal_iban)),
        ], limit=1)
        if not banking_account:
            _logger.exception(
                "Could not find a matching bank account with IBAN '%s' in connection '%s'.", journal_iban, connection.name,
            )
            raise UserError(
                _("Could not find a matching bank account with IBAN '%s' "
                "in connection '%s'. Please fetch accounts first.")
                % (journal_iban, connection.name)
            )
        return banking_account
    
    def _fetch_transaction_dtos(self, service, banking_account, date_since, date_until):
        """Fetch transaction DTOs from the banking service for the given account and date range."""
        _logger.info("Fetching transactions for %s from %s to %s", banking_account.iban, date_since, date_until)
        try:
            result = service.get_transactions(
                account_id=banking_account.external_account_id,
                date_from=date_since,
                date_to=date_until,
                max_pages=service.max_transaction_pages,
            )
            _logger.info("Fetched %s transactions for %s", len(result) if result else 0, banking_account.iban)
            return result
        except Exception as exc:
            _logger.exception(
                "Failed to fetch transactions for account %s (%s)", banking_account.name, banking_account.iban,
            )
            raise UserError(
                _("Failed to fetch transactions for account %s: %s") % (banking_account.name, str(exc))
            ) from exc
            
    def _enforce_history_limit(self, service, date_since: date) -> date:
        """Clamp date_since to the API's transaction history retention window."""
        limit_days: int | None = service.TRANSACTION_HISTORY_LIMIT_DAYS
        if limit_days is None:
            return date_since
        
        earliest_allowed = utc_today() - relativedelta(days=limit_days)
        if date_since >= earliest_allowed:
            return date_since
        
        is_scheduled = self.env.context.get('scheduled')
        if is_scheduled:
            _logger.warning(
                "Clamping date_since from %s to %s for provider '%s' "
                "(%s history limit: %d days)",
                date_since, earliest_allowed, self.name,
                service.__class__.__name__, limit_days,
            )
            return earliest_allowed
        
        raise UserError(_(
        "The start date cannot be more than %(days)d days in the past. "
        "%(backend)s does not retain transaction history older than %(days)d days.",
        days=limit_days,
        backend=service.__class__.__name__,
        ))

    def _enforce_minimum_lookback(self, service, date_since: date) -> date:
        """Widen date_since to the connector's minimum lookback window on scheduled pulls."""
        is_scheduled = self.env.context.get('scheduled')
        if not is_scheduled and not service.APPLY_LOOKBACK_TO_MANUAL_PULLS:
            return date_since

        lookback_days: int = service.TRANSACTION_LOOKBACK_DAYS
        if not lookback_days:
            return date_since

        earliest_allowed = utc_today() - relativedelta(days=lookback_days)
        if date_since <= earliest_allowed:
            return date_since

        _logger.info(
            "Widening date_since from %s to %s for provider '%s' "
            "(%s lookback: %d days)",
            date_since, earliest_allowed, self.name,
            service.__class__.__name__, lookback_days,
        )
        return earliest_allowed
