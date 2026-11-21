import logging

from odoo import _, api, fields, models

from ..services.constants.cron import CronPauseReason, CRON_FAILURE_THRESHOLD
from ..services.service_factory import _REGISTRY, BankingServiceFactory

_logger = logging.getLogger(__name__)

class OnlineBankStatementProviderCronGuard(models.Model):
    _inherit = 'online.bank.statement.provider'
    
    cron_paused = fields.Boolean(
        string="Cron Paused",
        default=False,
        help=(
            "When True, this provider is excluded from scheduled pulls."
        ),
    )
    
    cron_pause_reason = fields.Selection(
        selection=CronPauseReason.SELECTION,
        string="Pause Reason",
        readonly=True,
    )
    
    consecutive_failures = fields.Integer(
        string="Consecutive Failures",
        default=0,
        readonly=True,
    )
    
    cron_paused_since = fields.Datetime(
        string="Paused Since",
        readonly=True,
    )
    
    def action_resume_provider(self):
        """Manually resume a provider. Used in case of consecutive failures."""
        self.ensure_one()
        paused_since = self._resume_provider()
        self.message_post(
            body=_(
                "Scheduled pull manually re-enabled. "
                "Transactions since %(since)s will be fetched on the next scheduled run.",
                since=paused_since or _("unknown"),
            )
        )
        _logger.info("Provider '%s' manually resumed.", self.name)


    # TODO Important: the parent’s _adjust_schedule() and _schedule_next_run()
    #  add intervals to stored datetimes. For hourly/daily schedules
    #  with a configured timezone, that can shift the local run time 
    # across daylight-saving changes. To guarantee 1:00 AM/8:00 AM local time 
    # year-round, override those two methods to use next_scheduled_run() too.
    #  I’d include that in this commit and test the spring/fall DST boundaries;
    #  otherwise, document that exact DST alignment is not yet guaranteed.
    @api.model
    def _scheduled_pull(self):
        """
        Override the parent method to exclude cron-paused providers from scheduled pulls.
        
        !If the module gets updated and uses a newer online.bank.statement.provider parent module,
        the implementation of the parent method must be checked and this override alligned with changes.
        """
        self.search([
            ("active", "=", True),
            ("connection_id", "!=", False),
        ])._sync_backend_schedule()


        _logger.info(_("Scheduled pull of online bank statements..."))
        providers = self.search([
            ('active', '=', True),
            ('next_run', '<=', fields.Datetime.now()),
            ('cron_paused', '=', False),
        ])
        if providers:
            _logger.info(
                _("Pulling online bank statements of: %(provider_names)s"),
                dict(provider_names=", ".join(providers.mapped("journal_id.name"))),
            )
            for provider in providers.with_context(scheduled=True, tracking_disable=True):
                provider._adjust_schedule()
                date_since = (
                    provider.last_successful_run
                    if provider.last_successful_run
                    else provider.next_run - provider._get_next_run_period()
                )
                date_until = provider.next_run
                provider._pull(date_since, date_until)
        _logger.info(_("Scheduled pull of online bank statements complete."))
    
    def _log_provider_exception(self, exception, statement_date_since, statement_date_until):
        """Override the the parent's logging to also apply the cron guard."""
        super()._log_provider_exception(exception, statement_date_since, statement_date_until)
        
        is_scheduled = self.env.context.get('scheduled')
        if not is_scheduled:
            return

        self._handle_scheduled_exception(exception)
        
    def _handle_scheduled_exception(self, exception):
            """Classify the exception and apply the appropriate guard action."""
            self.ensure_one()
            connection = self._resolve_connection()

            if connection and BankingServiceFactory.is_consent_auth_error(connection, exception):
                self._pause_connection_providers(connection, reason=CronPauseReason.AUTH_ERROR)
            else:
                self._handle_consecutive_failure()
        
    def _handle_consecutive_failure(self):
        """Increment the failure counter. Pause the provider if threshold reached."""
        self.ensure_one()
        self.consecutive_failures += 1
        if self.consecutive_failures >= CRON_FAILURE_THRESHOLD:
            self._pause_provider(reason=CronPauseReason.CONSECUTIVE_FAILURES)

    def _pause_connection_providers(self, connection, reason):
        """Pause all providers linked to this connection."""
        providers = self.search([
            ('connection_id', '=', connection.id),
            ('cron_paused', '=', False),
        ])
        for provider in providers:
            provider._pause_provider(reason=reason)
            
    def _pause_provider(self, reason):
        """Pause provider and post a message."""
        self.ensure_one()
        CronPauseReason.validate(reason)
        self.write({
            'cron_paused': True,
            'cron_pause_reason': reason,
            'cron_paused_since': fields.Datetime.now(),
            'consecutive_failures': 0,
        })

        if reason == CronPauseReason.AUTH_ERROR:
            body = _(
                "The bank authorization has expired. Please re-authorize the connection. "
            )
        else:
            body = _(
                "Scheduled pull has been paused after %(threshold)d consecutive "
                "failures. Check logs.",
                threshold=CRON_FAILURE_THRESHOLD,
            )

        self.message_post(body=body)
        self._send_pause_notification()
        _logger.warning(
            "Provider '%s' cron paused. Reason: %s.",
            self.name, reason,
        )

    def _resume_provider(self):
        """Reset pause state and schedule the next run.

        Returns the previous `cron_paused_since` value, so callers can use it in messages.
        """
        self.ensure_one()
        paused_since = self.cron_paused_since
        self.write({
            'cron_paused': False,
            'cron_pause_reason': False,
            'cron_paused_since': False,
            'consecutive_failures': 0,
            'next_run': paused_since or fields.Datetime.now(),
        })
        return paused_since
    
    def _send_pause_notification(self):
        """Send a notification email to the account manager group."""
        self.ensure_one()
        template = self.env.ref(
            'l10n_fi_bank_connectors.mail_template_provider_paused',
            raise_if_not_found=False,
        )
        if not template:
            _logger.warning(
                "Provider '%s': notification template not found, skipping email.", self.name,
                )
            return
        
        group = self.env.ref('account.group_account_manager', raise_if_not_found=False)
        if not group:
            _logger.warning(
                "Provider '%s': account manager group not found, skipping email.",
                self.name,
            )
            return
        
        recipients = group.users.filtered(
            lambda u: u.email and u.company_id == self.company_id
        )
        if not recipients:
            _logger.warning(
                "Provider '%s': no account managers with email found for company '%s', "
                "skipping email.", self.name, self.company_id.name,
            )
            return
        partner_ids = recipients.mapped('partner_id').ids
        template.send_mail(
            self.id,
            email_values={'recipient_ids': [(6, 0, partner_ids)]},
            force_send=False,
        )
        _logger.info(
            "Provider '%s': pause notification queued for %d recipient(s).",
            self.name, len(partner_ids),
        )

    def _schedule_next_run(self):
        """Override to reset the failure counter in a successful pull."""
        super()._schedule_next_run()
        if self.consecutive_failures > 0:
            self.consecutive_failures = 0
            _logger.debug(
                "Provider '%s': consecutive failure counter reset after successful pull.", self.name,
            )
