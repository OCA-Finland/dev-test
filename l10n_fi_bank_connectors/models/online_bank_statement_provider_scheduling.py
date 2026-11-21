import logging

from odoo import api, fields, models

from ..services.constants.backend_schedules import (
    next_daily_run,
    schedule_for_family,
)

_logger = logging.getLogger(__name__)


class OnlineBankStatementProviderScheduling(models.Model):
    _inherit = "online.bank.statement.provider"

    interval_type = fields.Selection(readonly=True)
    interval_number = fields.Integer(readonly=True)
    backend_schedule_signature = fields.Char(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        providers = super().create(vals_list)
        providers._sync_backend_schedule()
        return providers

    def write(self, vals):
        result = super().write(vals)
        self._sync_backend_schedule()
        return result

    def _sync_backend_schedule(self):
        for provider in self:
            if not provider.connection_id:
                continue

            schedule = schedule_for_family(provider.connection_id.backend_family)
            if schedule is None:
                _logger.warning(
                    "No backend schedule for family %r (provider %s); skipping schedule sync.",
                    provider.connection_id.backend_family, provider.id,
                )
                continue

            signature = f"{schedule.run_hour}|{schedule.run_minute}|{schedule.tz_name}"

            vals = {
                "interval_number": 1,
                "interval_type": "days",
                "backend_schedule_signature": signature,
            }

            if provider.backend_schedule_signature != signature:
                base = provider.last_successful_run or fields.Datetime.now()
                vals["next_run"] = next_daily_run(schedule, base)

            super(OnlineBankStatementProviderScheduling, provider).write(vals)