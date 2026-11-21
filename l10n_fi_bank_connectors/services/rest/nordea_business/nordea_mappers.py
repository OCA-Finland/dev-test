from .constants.nordea_payments import NordeaPaymentStatus
from .nordea_dtos import (
    NordeaAccountDTO, 
    NordeaPaymentResponseDTO, 
    NordeaTransactionDTO)
from ....utils.formatting import (
    parse_date, 
    to_decimal, 
    map_status_or_unrecognized,
    normalize_iban
    )


class NordeaMappers:
    """Maps Nordea Business API responses to internal data transfer objects."""
    
    def _map_account(self, raw: dict) -> NordeaAccountDTO:
        """Convert raw account data to NordeaAccountDTO."""
        iban = ""
        for acct_num in raw.get("account_numbers", []):
            if acct_num.get("_type") == "IBAN":
                iban = normalize_iban(acct_num.get("value", ""))
                break

        balance_val = raw.get("booked_balance")
        if balance_val is not None:
            balance = to_decimal(balance_val)
        else:
            balance = None

        dto = NordeaAccountDTO(
            external_id=raw.get("_id", ""),
            iban=iban,
            bic=raw.get("bank", {}).get("bic", ""),
            currency=raw.get("currency", "EUR"),
            name=raw.get("account_name") or iban,
            product=raw.get("product", ""),
            balance=balance,
            raw=raw,
            available_balance=to_decimal(raw.get("available_balance")),
            value_dated_balance=to_decimal(raw.get("value_dated_balance")),
            account_type=raw.get("account_type") or "",
            status=raw.get("status") or "",
            credit_limit=to_decimal(raw.get("credit_limit")),
            country=raw.get("country") or "",
            latest_transaction_booking_date=parse_date(raw.get("latest_transaction_booking_date")),
        )
        return dto

    def _map_transaction(self, raw: dict) -> NordeaTransactionDTO:
        """Convert raw transaction data to TransactionDTO."""
        return NordeaTransactionDTO(
            transaction_id=raw.get("transaction_id", "") or raw.get("archive_id"),
            booking_date=parse_date(raw.get("booking_date")),
            value_date=parse_date(raw.get("value_date")),
            # transaction_type_code​ field exists​ but the docs does not specify possible values and the FAQ says: 
            # "These values vary depending on multiple factors, including account ledgers, and therefore we cannot supply 
            # a definitive list.", so we use the type_description​ field (the docs says: example: ATM Cash Withdrawal, 
            # Description of the type of transaction, e.g. Cash withdrawal, Account transfer, etc. (localized))
            transaction_type=raw.get("type_description") or "",
            # TODO Nordea provides only "counterparty_account", its structure unclear
            account_number="",
            payment_ref=raw.get("reference") or "",
            ref="",  # TODO: candidates are "message" (remitter->beneficiary text) or "narrative"
                 # (customer custom message).
            amount=to_decimal(raw.get("amount", "0")),
            amount_currency=raw.get("currency", "EUR"),
            partner_name=raw.get("counterparty_name") or "",
            raw=raw,
            balance_after=to_decimal(raw.get("balance_after_transaction")),     # Nordea has not implemented for FI, leaving it here for now
            status=raw.get("status") or "",
        )
    
    
    @staticmethod
    def _extract_payment_obj_and_links(raw: dict, *, from_list: bool = False):
        """Return (payment_obj, signing_url) for any Nordea payment response."""
        response = raw.get("response", {})

        if from_list:
            payments = response.get("payments") or []
            payment_obj = payments[0] if payments else {}
            links = payment_obj.get("_links") or []
        else:
            payment_obj = response
            links = raw.get("_links") or []

        signing_url = next(
            (lnk["href"] for lnk in links if lnk.get("rel") == "signing"),
            None,
        )
        return payment_obj, signing_url
    
    def _map_payment_response(self,raw: dict,banking_payment_id: str = "",*,from_list: bool = False,) -> NordeaPaymentResponseDTO:
        """Convert raw payment response to NordeaPaymentResponseDTO."""
        payment_obj, signing_url = self._extract_payment_obj_and_links(
            raw, from_list=from_list
        )

        return NordeaPaymentResponseDTO(
            status_reason=payment_obj.get("payment_status_reason"),
            reason_narrative=payment_obj.get("reason_narrative"),
            tpp_messages=payment_obj.get("tpp_messages") or [],
            status=map_status_or_unrecognized(NordeaPaymentStatus.TO_INTERNAL, payment_obj.get("payment_status", "")),
            banking_payment_id=banking_payment_id,
            signing_url=signing_url,
            raw=raw,
        )
