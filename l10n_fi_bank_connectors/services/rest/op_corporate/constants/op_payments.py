from ....constants.payments import PaymentStatus

class OPPaymentLimits:
    """Payment field limits for OP Corporate API."""
    MAX_REFERENCE_LENGTH = 25
    MAX_MESSAGE_LENGTH = 140
    MAX_AMOUNT_INTEGER_DIGITS = 13
    
class OPPaymentStatus:
    """
    Raw payment status values returned by the OP Corporate API
    and their mapping to internal statuses.
    """
    PROCESSING = 'PROCESSING'
    PROCESSED = 'PROCESSED'
    REJECTED = 'REJECTED'

    TO_INTERNAL = {
        PROCESSING: PaymentStatus.PROCESSING,
        PROCESSED: PaymentStatus.PROCESSED,
        REJECTED: PaymentStatus.REJECTED,
    }