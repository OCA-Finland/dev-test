from ..utils.id_generation import generate_unique_id


class PaymentIdGen:
    """Provides generate_unique_identification for providers that generate their own payment ID."""

    def generate_unique_identification(self, payment) -> None:
        """Generate and persist the banking_payment_id if not already set."""
        if not payment.banking_payment_id:
            payment.banking_payment_id = generate_unique_id()
            payment.flush_recordset(['banking_payment_id'])