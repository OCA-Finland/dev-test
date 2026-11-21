from ....constants.payments import PaymentStatus

class NordeaFIPaymentLimits:
    """
    Payment field limits for Nordea FI SEPA payments.
    Only FI SEPA is implemented. (SE, DK, NO to be done)
    """
    MAX_CREDITOR_MESSAGE_LENGTH = 140
    MAX_AMOUNT_INTEGER_DIGITS = 9

class NordeaUrgency:
    """Urgency values for Nordea SEPA payments."""
    STANDARD = 'standard'
    EXPRESS = 'express'
    SAMEDAY = 'sameday'

    ALL = {STANDARD, EXPRESS, SAMEDAY}
    
class NordeaPaymentStatus:
    """
    Payment status values returned by the Nordea Business API
    and their mapping to internal statuses.
    """
    # init payment or get a payment/payments
    PENDING_CONFIRMATION = 'PendingConfirmation'
    # confirm initiated payments or get a payment/payments
    PENDING_USER_APPROVAL = 'PendingUserApproval'
    # get a payment/payments
    ON_HOLD = 'OnHold'
    CONFIRMED = 'Confirmed'
    PARTIALLY_CONFIRMED = 'PartiallyConfirmed'
    PAID = 'Paid'
    REJECTED = 'Rejected'
    INSUFFICIENT_FUNDS = 'InsufficientFunds'
    LIMIT_EXCEEDED = 'LimitExceeded'
    USER_APPROVAL_FAILED = 'UserApprovalFailed'
    USER_APPROVAL_TIMEOUT = 'UserApprovalTimeout'
    USER_APPROVAL_CANCELLED = 'UserApprovalCancelled'
    UNCONFIRMED = 'Unconfirmed'
    UNKNOWN = 'Unknown'

    TO_INTERNAL = {
        PAID: PaymentStatus.PAID,
        CONFIRMED: PaymentStatus.CONFIRMED,
        PARTIALLY_CONFIRMED: PaymentStatus.PARTIALLY_CONFIRMED,
        PENDING_CONFIRMATION: PaymentStatus.PENDING_CONFIRMATION,
        PENDING_USER_APPROVAL: PaymentStatus.PENDING_USER_APPROVAL,
        ON_HOLD: PaymentStatus.ON_HOLD,
        REJECTED: PaymentStatus.REJECTED,
        INSUFFICIENT_FUNDS: PaymentStatus.INSUFFICIENT_FUNDS,
        USER_APPROVAL_FAILED: PaymentStatus.USER_APPROVAL_FAILED,
        USER_APPROVAL_TIMEOUT: PaymentStatus.USER_APPROVAL_TIMEOUT,
        USER_APPROVAL_CANCELLED: PaymentStatus.USER_APPROVAL_CANCELLED,
        LIMIT_EXCEEDED: PaymentStatus.LIMIT_EXCEEDED,
        UNCONFIRMED: PaymentStatus.UNCONFIRMED,
        UNKNOWN: PaymentStatus.UNKNOWN,
    }