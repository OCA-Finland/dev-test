class NordeaTransactionStatus:
    """
    Transaction status returned by the Nordea Business AIS transactions endpoint.
    
    According to Nordea docs (mostly extrapolated from FAQ):
    - reserved: preliminarily booked transactions that have not yet fully settled or posted to the final balance
    - confirmed: docs do not explain the meaning, but according to FAQ are a final state and should be treated identical to billed
    - billed: transaction is fully booked and processed into the corporate account ledger
    """
    RESERVED = "reserved"
    CONFIRMED = "confirmed"
    BILLED = "billed"

    FINAL_STATUSES = frozenset({CONFIRMED, BILLED})