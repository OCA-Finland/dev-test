import logging

from ...constants.payments import PaymentStatus

from .constants.pain002 import (
    GROUP_STATUS_ACTC,
    GROUP_STATUS_RJCT,
    PAYMENT_STATUS_ACCP,
    PAYMENT_STATUS_ACSP,
    PAYMENT_STATUS_ACWC,
    PAYMENT_STATUS_PART,
    PAYMENT_STATUS_PDNG,
    PAYMENT_STATUS_RJCT,
    REASON_AM04,
    TRANSACTION_STATUS_ACCP,
    TRANSACTION_STATUS_ACSP,
    TRANSACTION_STATUS_ACWC,
    TRANSACTION_STATUS_PDNG,
    TRANSACTION_STATUS_RJCT,
)
from .constants.pain002 import (
    STATUS_ACSC,
)
from ...dtos import PaymentResponseDTO
from .nordea_ca_dtos import (
    ApplicationResponseDTO,
    NordeaCAPaymentResponseDTO,
    NordeaCATransactionDTO,
    PaymentStatusReportDTO,
)

_logger = logging.getLogger(__name__)

class NordeaCAMappers:
    """Maps CAMT.053 entries to internal data transfer objects."""

    @staticmethod
    def _map_pain002_status(status: str | None, level: str, reasons=()) -> str:
        """Map a pain.002 status at group, payment, or transaction level."""
        reason_codes = {
            reason.code for reason in reasons if reason and reason.code
        }

        if status in {GROUP_STATUS_RJCT, PAYMENT_STATUS_RJCT, TRANSACTION_STATUS_RJCT}:
            return (
                PaymentStatus.INSUFFICIENT_FUNDS
                if REASON_AM04 in reason_codes
                else PaymentStatus.REJECTED
            )

        if status in {PAYMENT_STATUS_PDNG, TRANSACTION_STATUS_PDNG}:
            if level == "payment":
                # Nordea MIG 7.1.3: payment-level PDNG means the whole Payment
                # Information level (with all its transactions) is awaiting final
                # confirmation by the Company, so a person must confirm it at Nordea.
                # 7.1.3 mentions "waiting for funds" only for transaction-level PDNG,
                # so reason codes (e.g. AM04) are deliberately ignored here.
                _logger.info(
                    "pain.002 payment-level PDNG mapped to PENDING_USER_APPROVAL "
                    "(reason codes ignored: %s)",
                    sorted(reason_codes),
                )
                return PaymentStatus.PENDING_USER_APPROVAL

            if level == "group":
                # MIG 7.1.3 lists only ACTC and RJCT at group level, so group-level
                # PDNG is not expected from Nordea. ISO allows it, so it is handled
                # like transaction-level PDNG below and logged to make it visible.
                _logger.warning(
                    "Unexpected pain.002 group-level PDNG (reason codes: %s)",
                    sorted(reason_codes),
                )

            # Transaction level (MIG 7.1.3): PDNG means either "awaiting final
            # confirmation by the Company" or "waiting for funds on the debit account".
            # Only the funds case is recognisable (reason AM04); a confirmation case
            # without AM04 therefore maps to PROCESSING (known limitation).
            return (
                PaymentStatus.INSUFFICIENT_FUNDS
                if REASON_AM04 in reason_codes
                else PaymentStatus.PROCESSING
            )

        if status == GROUP_STATUS_ACTC:
            return PaymentStatus.PROCESSING

        if status in {
            PAYMENT_STATUS_ACCP,
            PAYMENT_STATUS_ACWC,
            TRANSACTION_STATUS_ACCP,
            TRANSACTION_STATUS_ACWC,
        }:
            return PaymentStatus.CONFIRMED

        if status in {
            PAYMENT_STATUS_ACSP,
            TRANSACTION_STATUS_ACSP,
        }:
            return PaymentStatus.PROCESSING

        if status == PAYMENT_STATUS_PART and level == "payment":
            return PaymentStatus.PARTIALLY_CONFIRMED

        if status == STATUS_ACSC:
            # ACSC is not listed in Nordea MIG 7.1.3, so it is not expected in real
            # files. ISO defines it as "settlement completed", which is stricter than
            # the "pending final execution" meaning of CONFIRMED. It is mapped to
            # CONFIRMED defensively until a real file shows otherwise.
            _logger.warning(
                "Undocumented pain.002 status ACSC at level=%s mapped to CONFIRMED", level
            )
            return PaymentStatus.CONFIRMED

        _logger.warning("Unrecognized pain.002 status=%s at level=%s", status, level)
        return PaymentStatus.UNRECOGNIZED


    def _map_transaction(self, entry: dict) -> NordeaCATransactionDTO:
        """Convert one parsed camt.053 entry into a transaction DTO."""

        details = entry.get("details") or []
        detail = details[0] if details else {}

        credit_debit = entry.get("credit_debit")
        is_debit = credit_debit == "DBIT"       # TODO extract

        party = (
            detail.get("ultimate_debtor" if is_debit else "ultimate_creditor")
            or detail.get("creditor" if is_debit else "debtor")
            or {}
        )
        party_account = detail.get(
            "creditor_account" if is_debit else "debtor_account"
        ) or {}

        remittance = detail.get("remittance") or {}
        structured = remittance.get("structured") or []
        unstructured = remittance.get("unstructured") or []

        payment_ref = next(
            (
                item.get("reference")
                for item in structured
                if item.get("reference")
            ),
            "",
        )

        return NordeaCATransactionDTO(
            transaction_id=(
                entry.get("account_servicer_reference")
                or entry.get("transaction_id")
            ),
            booking_date=entry.get("booking_date"),
            value_date=entry.get("value_date"),
            amount=entry.get("amount"),                    # The parser already applies DBIT/CRDT sign.
            amount_currency=entry.get("currency") or "",
            account_number=(
                party_account.get("iban")
                or party_account.get("other_account")
            ),
            payment_ref=payment_ref,
            ref=" ".join(unstructured),
            partner_name=party.get("name") or "",
            raw=entry,
        )

    def _map_payment_response(self, response_dto: ApplicationResponseDTO) -> NordeaCAPaymentResponseDTO:
        """
        Map a parsed NCA ApplicationResponse (UploadFile ack) to NordeaCAPaymentResponseDTO.
        This only ever receives a successful ack — initiate_payment() raises before
        calling this if response_code != OK — so it always maps to PROCESSING:
        submission was accepted, but the actual payment outcome is not known yet
        and arrives later via pain.002 status ingestion (Ticket 8).
        """
        return NordeaCAPaymentResponseDTO(
            status=PaymentStatus.PROCESSING,
            response_code=response_dto.response_code,
            response_text=response_dto.response_text or "",
            raw=response_dto.__dict__,
        )

    @staticmethod
    def _pain002_reasons_to_raw(reasons) -> list[dict]:
        """Serialise StatusReasonDTOs to plain dicts so they can be stored in the payment log."""
        return [
            {"code": reason.code, "additional_info": list(reason.additional_info)}
            for reason in reasons
        ]

    def _map_pain002_report(self, report: PaymentStatusReportDTO) -> list[PaymentResponseDTO]:
        """
        Flatten one parsed pain.002 report into one PaymentResponseDTO per reported payment.

        Pure mapping, no DB access. Matching to account.payment records is a separate step.
        The most specific level present wins (transaction, then payment, then group), as the
        message-level ISO rules (C10-C21) forbid a lower level from contradicting a higher
        level rejection within one message. Only the winning level's status is mapped.
        Since HT00238 one generated ID is used as MsgId, PmtInfId, EndToEndId and InstrId,
        so any of them correlates to banking_payment_id; the group level uses OrgnlMsgId.
        """
        responses: list[PaymentResponseDTO] = []

        # Report-wide context stored with every response (needed later for out-of-order
        # handling and for showing reasons, see items 10 and 15).
        base_raw = {
            "message_id": report.message_id,
            "original_message_id": report.original_message_id,
            "created_at": report.created_at.isoformat() if report.created_at else None,
            "group_status": report.group_status,
        }

        def _build(banking_payment_id, level, code, reasons, **extra):
            """Create one response, or skip (with a warning) if no id is available."""
            if not banking_payment_id:
                _logger.warning(
                    "Skipping pain.002 %s-level entry without a usable ID "
                    "(report message_id=%s, status=%s)",
                    level, report.message_id, code,
                )
                return
            status = self._map_pain002_status(code, level, reasons)
            _logger.info(
                "pain.002 entry: banking_payment_id=%s level=%s code=%s -> %s",
                banking_payment_id, level, code, status,
            )
            responses.append(
                PaymentResponseDTO(
                    status=status,
                    banking_payment_id=banking_payment_id,
                    raw={
                        **base_raw,
                        "level": level,
                        "code": code,
                        "reasons": self._pain002_reasons_to_raw(reasons),
                        **extra,
                    },
                )
            )

        # Group only: no payment entries (e.g. ACTC on file reception or a whole-file RJCT).
        if not report.payments:
            _build(report.original_message_id, "group", report.group_status, report.reasons)
            return responses

        for payment in report.payments:
            # Payment level only: no transaction entries below it.
            if not payment.transactions:
                _build(
                    payment.payment_info_id, "payment", payment.status, payment.reasons,
                    payment_info_id=payment.payment_info_id,
                )
                continue

            # Transaction level wins over payment and group level.
            for tx in payment.transactions:
                # Our IDs are identical at all levels, so a difference is unexpected.
                if tx.instruction_id and tx.end_to_end_id and tx.instruction_id != tx.end_to_end_id:
                    _logger.warning(
                        "pain.002 InstrId %s differs from EndToEndId %s (PmtInfId=%s)",
                        tx.instruction_id, tx.end_to_end_id, payment.payment_info_id,
                    )
                tx_id = tx.end_to_end_id
                if not tx_id:
                    # Assumption: falling back to PmtInfId is safe because of HT00238.
                    _logger.warning(
                        "pain.002 transaction without EndToEndId, falling back to PmtInfId %s",
                        payment.payment_info_id,
                    )
                    tx_id = payment.payment_info_id
                _build(
                    tx_id, "transaction", tx.status, tx.reasons,
                    payment_info_id=payment.payment_info_id,
                    payment_status=payment.status,
                    instruction_id=tx.instruction_id,
                )

        return responses