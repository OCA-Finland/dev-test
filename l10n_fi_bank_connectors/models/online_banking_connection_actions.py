import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.constants.connection import ConnectionStatus
from ..services.constants.credentials import CredentialType
from ..services.constants.backend_schedules import next_daily_run, schedule_for_family
from ..services.error_handling.error_types import AccountRefreshNotSupported
from ..services.service_factory import BankingServiceFactory


_logger = logging.getLogger(__name__)


class OnlineBankingConnectionActions(models.Model):
    _inherit = 'online.banking.connection'


    # test connection
    def action_test_connection(self):
        self.ensure_one()
        try:
            with BankingServiceFactory.from_record_ctx(self) as service:
                if hasattr(service, 'probe_auth'):
                    response_dto = service.probe_auth()
                    self._mark_active()
                    _logger.info("Auth probe successful for connection %s using %s (code=%s)", self.name, service.provider_name, response_dto.response_code,)
                    return {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": _("Authentication OK"),
                            "message": _(
                                "%(p)s responded: %(code)s - %(text)s. Account fetching is not yet available.",
                                p=service.provider_name,
                                code=response_dto.response_code,
                                text=response_dto.response_text,
                            ),
                            "type": "success",
                            "sticky": False,
                            "next": {"type": "ir.actions.act_window_close"},
                        },
                    }
                accounts = service.get_accounts()
                self._mark_active()
                _logger.info("Connection test successful: %d accounts found using %s", len(accounts), service.provider_name,)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection OK"),
                    "message": _(
                        "Connection successful. %(n)d account(s) found on %(p)s.",
                        n=len(accounts), p=service.provider_name,
                    ),
                    "type": "success",
                    "sticky": False,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        except Exception as e:
            _logger.exception("Connection test failed")
            raise UserError(_("Connection test failed: %s") % e) from e

    def _mark_active(self):
        self.sudo().write({
            'status': ConnectionStatus.ACTIVE,
            'last_auth_attempt': fields.Datetime.now(),
        })


    # fetch accounts
    def action_fetch_accounts(self):
        self.ensure_one()
        try:
            total, imported, updated = self._fetch_and_sync_accounts()
            self._mark_active()

            if not total:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("No Accounts Found"),
                        "message": _("No accounts were returned from the API."),
                        "type": "warning",
                        "sticky": False,
                    },
                }

            msg = _("Successfully synced %(total)d account(s).", total=total)
            if imported:
                msg += _("\n• %(new)d new account(s)", new=imported)
            if updated:
                msg += _("\n• %(upd)d updated", upd=updated)

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Accounts Synced"),
                    "message": msg,
                    "type": "success",
                    "sticky": False,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        except Exception as e:
            _logger.exception("Failed to fetch accounts")
            raise UserError(_("Failed to fetch accounts: %s") % e) from e

    def _fetch_and_sync_accounts(self):
        """Fetch and upsert account information; update the timestamp on success."""
        self.ensure_one()

        with BankingServiceFactory.from_record_ctx(self) as service:
            account_dtos = service.refresh_accounts()

        imported, updated = self._process_account_dtos(account_dtos)

        self.account_info_last_synced_at = fields.Datetime.now()
        self.invalidate_recordset(["bank_account_ids", "bank_account_count"])

        return len(account_dtos), imported, updated


    # Nordea API authorization
    def action_authorize_nordea(self):
        self.ensure_one()
        if not isinstance(self.id, int):
            raise UserError(_("Please save the connection before starting authorization."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "nordea.oauth.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_connection_id": self.id},
        }


    # credentials
    def action_set_credential(self, credential_type: str):
        self.ensure_one()
        if not isinstance(self.id, int):
            raise UserError(_("Please save the connection before setting credentials."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "online.banking.credential.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_connection_id":   self.id,
                "default_credential_type": credential_type,
            },
        }
    
    def action_clear_pem_credentials(self):
        self.ensure_one()
        self.credential_ids.filtered(
            lambda c: c.credential_type in (
                CredentialType.OP_MTLS_CERT_PEM,
                CredentialType.OP_MTLS_KEY_PEM,
            )
        ).unlink()
        return True

    def action_clear_nca_pem_credentials(self):
        self.ensure_one()
        self.credential_ids.filtered(
            lambda c: c.credential_type in (
                CredentialType.NORDEA_CA_CERT_PEM,
                CredentialType.NORDEA_CA_KEY_PEM,
            )
        ).unlink()
        return True
    
    def action_set_client_id(self):
        return self.action_set_credential(CredentialType.CLIENT_ID)

    def action_set_secret(self):
        return self.action_set_credential(CredentialType.CLIENT_SECRET)

    def action_set_signing_key(self):
        return self.action_set_credential(CredentialType.OP_PAYMENT_SIGNING_KEY)

    def action_set_signing_kid(self):
        return self.action_set_credential(CredentialType.OP_PAYMENT_SIGNING_KID)

    def action_set_cert_pem(self):
        return self.action_set_credential(CredentialType.OP_MTLS_CERT_PEM)

    def action_set_key_pem(self):
        return self.action_set_credential(CredentialType.OP_MTLS_KEY_PEM)

    def action_set_nordea_auth_signing_key(self):
        return self.action_set_credential(CredentialType.NORDEA_AUTH_SIGNING_KEY)

    def action_set_nca_cert_pem(self):
        return self.action_set_credential(CredentialType.NORDEA_CA_CERT_PEM)

    def action_set_nca_key_pem(self):
        return self.action_set_credential(CredentialType.NORDEA_CA_KEY_PEM)

    def action_set_nca_signer_id(self):
        return self.action_set_credential(CredentialType.NORDEA_CA_SIGNER_ID)

    def action_set_nca_sender_id(self):
        return self.action_set_credential(CredentialType.NORDEA_CA_SENDER_ID)

    def action_add_nca_account(self):
        self.ensure_one()
        if not isinstance(self.id, int):
            raise UserError(_("Please save the connection before adding an account."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "online.banking.account.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_connection_id": self.id},
        }


    @api.model
    def _cron_refresh_account_info(self):
        connections = self.search([
            ("status", "=", ConnectionStatus.ACTIVE),
            ("account_info_next_run", "<=", fields.Datetime.now()),
        ])
        for connection in connections:
            connection._refresh_account_info_scheduled()

    def _refresh_account_info_scheduled(self):
        self.ensure_one()
        schedule = schedule_for_family(self.backend_family)
        if schedule is None:
            _logger.warning(
                "No backend schedule for family %r (connection %s); skipping account info refresh.",
                self.backend_family, self.id,
            )
            return

        try:
            with self.env.cr.savepoint():
                total, imported, updated = self._fetch_and_sync_accounts()
        except AccountRefreshNotSupported:
            _logger.info(
                "Account info refresh not supported: connection_id=%s backend_family=%s",
                self.id, self.backend_family,
            )
        except Exception:
            _logger.exception(
                "Scheduled account-info refresh failed for connection_id=%s backend_family=%s",
                self.id, self.backend_family,
            )
        else:
            _logger.info(
                "Account info refreshed: connection_id=%s backend_family=%s "
                "accounts=%s imported=%s updated=%s",
                self.id, self.backend_family, total, imported, updated,
            )

        self.account_info_next_run = next_daily_run(schedule, fields.Datetime.now())