import logging

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.base_banking_service import (
    PaymentRequestDTO,
    PaymentResponseDTO,
)
from ..services.constants.payments import (
    BANKING_ID_REUSE_WINDOW_DAYS,
    AccountPaymentState,
    PaymentStatus,
)
from ..utils.formatting import to_decimal, normalize_iban

_logger = logging.getLogger(__name__)


class AccountPaymentHelpers(models.Model):
    _inherit = 'account.payment'

    def _assert_sendable(self):
        """Validate that the payment can be sent to the bank."""
        if self.state not in AccountPaymentState.SENDABLE:
            raise UserError(_("Only confirmed payments can be sent. Please confirm the payment first."))
        if self.banking_payment_status == PaymentStatus.PROCESSED:
            raise UserError(_("This payment has already been processed."))

    def _assert_record_complete(self):
        """
        Ensure the payment record contains all required banking fields: 
        partner, partner bank account, journal bank account.
        """
        if not self.partner_id:
            raise UserError(_("Payment has no partner set."))

        if not self.partner_bank_id and not self.env['res.partner.bank'].search([
            ('partner_id', '=', self.partner_id.id),
        ], limit=1):
            raise UserError(_("Partner '%s' has no bank account configured.") % self.partner_id.name)

        if not self.journal_id:
            raise UserError(_("This payment has no journal configured."))

        if not self.journal_id.bank_account_id or not self.journal_id.bank_account_id.acc_number:
            raise UserError(_("Journal '%s' has no bank account configured.")% self.journal_id.name)

    def _get_connection(self):
        if self.banking_connection_id:
            return self.banking_connection_id
        connection = self._get_connection_from_journal()
        if connection:
            return connection
        raise UserError(
            _("No banking connection found for journal '%s'. "
              "Please configure a bank feed provider under "
              "Accounting → Configuration → Journals.")
            % self.journal_id.name
        )

    def _get_connection_from_journal(self):
        """Resolve the banking connection from the payment's journal provider."""
        journal = self.journal_id
        if not journal:
            return None
        provider = journal.online_bank_statement_provider_id
        if not provider:
            return None
        return provider._resolve_connection()

    def _get_partner_iban(self) -> str:
        if self.partner_bank_id and self.partner_bank_id.acc_number:
            return self.partner_bank_id.acc_number
        bank_account = self.env['res.partner.bank'].search([
            ('partner_id', '=', self.partner_id.id),
        ], limit=1)
        if not bank_account:
            raise UserError(_("Partner '%s' has no bank account configured.")% self.partner_id.name)
        return normalize_iban(bank_account.acc_number)

    def _get_debtor_iban(self) -> str:
        return self.journal_id.bank_account_id.acc_number

    def _build_dto(self, service) -> PaymentRequestDTO:
        base_kwargs = dict(
            creditor_name=self.partner_id.name or "",
            creditor_iban=self._get_partner_iban(),
            debtor_iban=self._get_debtor_iban(),
            debtor_name=self.company_id.name or "",
            amount=to_decimal(self.amount),
            currency=self.currency_id.name,
            reference=(self.payment_reference or "").strip(),
            message=(self.memo or "").strip(),
            request_execution_date=self.date,
        )

        dto_class = service.payment_request_dto_class()
        extra_kwargs = service.extra_payment_request_kwargs(self)
        return dto_class(**base_kwargs, **extra_kwargs)
    
    def _apply_payment_response(self, response: PaymentResponseDTO, event_type: str):
        """Updates payment status and appends a payment log entry."""
        status = self._apply_status(response)
        
        if not self.banking_payment_id and response.banking_payment_id:
            self.banking_payment_id = response.banking_payment_id
            self.flush_recordset(['banking_payment_id'])
        
        if status in (
            PaymentStatus.REJECTED, 
            PaymentStatus.UNRECOGNIZED,
            PaymentStatus.INSUFFICIENT_FUNDS,
            PaymentStatus.LIMIT_EXCEEDED,
            PaymentStatus.USER_APPROVAL_FAILED,
            PaymentStatus.USER_APPROVAL_TIMEOUT,
            PaymentStatus.USER_APPROVAL_CANCELLED
            ):
            _logger.warning(
                "Payment not accepted: payment_id=%s status=%s raw=%s",
                self.id,
                status,
                response.raw,
            )
        connection = self.banking_connection_id
        provider = connection.api_backend if connection else ""
        self.env['online.bank.payment.log']._append_payment_log(
            payment=self,
            provider=provider,
            event_type=event_type,
            signing_url=getattr(response, 'signing_url', None) or "",
            status=status,
            raw_bytes=response.raw_bytes,
        )

    def _apply_status(self, response: PaymentResponseDTO) -> str:
        status = response.status or PaymentStatus.PROCESSING
        if status not in dict(PaymentStatus.SELECTION):
            _logger.warning(
                "Unrecognized internal status '%s' for banking_payment_id %s — defaulting to UNRECOGNIZED",
                status, self.banking_payment_id,
            )
            status = PaymentStatus.UNRECOGNIZED
        self.banking_payment_status = status
        return status

    @api.depends('online_bank_payment_log_ids.signing_url')
    def _compute_banking_signing_url(self):
        for payment in self:
            latest = payment.online_bank_payment_log_ids.filtered('signing_url')[:1]
            payment.banking_signing_url = latest.signing_url or False

    @api.model
    def _find_payment_by_banking_id(self, banking_payment_id, connection):
        """
        Find the payment a bank-side ID refers to. Returns one record or an empty recordset.

        banking_payment_id is deliberately not unique (Nordea reuses IDs after 90 days),
        so the lookup is scoped to the banking connection and to payments created within
        BANKING_ID_REUSE_WINDOW_DAYS. If several still match, the newest one wins and a
        warning is logged. Nothing is applied here; this is a pure lookup.
        """
        if not banking_payment_id or not connection:
            _logger.warning(
                "Payment lookup skipped: banking_payment_id=%r connection=%s",
                banking_payment_id, connection.id if connection else None,
            )
            return self.browse()

        base_domain = [
            ('banking_payment_id', '=', banking_payment_id),
            ('banking_connection_id', '=', connection.id),
        ]
        window_start = fields.Datetime.now() - timedelta(days=BANKING_ID_REUSE_WINDOW_DAYS)
        candidates = self.search(
            base_domain + [('create_date', '>=', window_start)],
            order='create_date desc, id desc',
        )

        if not candidates:
            # Distinguish "unknown ID" from "known ID outside the window" in the logs.
            if self.search_count(base_domain):
                _logger.warning(
                    "banking_payment_id=%s exists on connection %s but only on payments "
                    "created more than %s days ago, not matched",
                    banking_payment_id, connection.id, BANKING_ID_REUSE_WINDOW_DAYS,
                )
            else:
                _logger.info(
                    "No payment found for banking_payment_id=%s on connection %s",
                    banking_payment_id, connection.id,
                )
            return self.browse()

        if len(candidates) > 1:
            _logger.warning(
                "banking_payment_id=%s matches %s payments on connection %s within %s days "
                "(ids=%s); using the newest (id=%s)",
                banking_payment_id, len(candidates), connection.id,
                BANKING_ID_REUSE_WINDOW_DAYS, candidates.ids, candidates[0].id,
            )
        return candidates[0]

    @api.model
    def _match_pain002_responses(self, responses, connection):
        """
        Match PaymentResponseDTOs built from a pain.002 report to payments.

        Returns (matched, unmatched): matched is a list of (payment, response) pairs,
        unmatched is the list of responses without a payment. Nothing is applied here;
        applying and the log-and-skip handling of unmatched IDs belong to the ingestion
        loop (HT00142 item 11).
        """
        matched = []
        unmatched = []
        for response in responses:
            payment = self._find_payment_by_banking_id(response.banking_payment_id, connection)
            if payment:
                matched.append((payment, response))
            else:
                unmatched.append(response)
        _logger.info(
            "pain.002 matching on connection %s: %s matched, %s unmatched",
            connection.id if connection else None, len(matched), len(unmatched),
        )
        return matched, unmatched