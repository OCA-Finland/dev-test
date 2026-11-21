POLL_INTERVAL_MINUTES = 5
MAX_POLL_AGE_HOURS = 48

# for OP API statuses see https://op-developer.fi/products/banking/docs/op-corporate-payment-api#operation/paymentV3
# fOR NORDEA api SEE https://documentation.nordeaopenbanking.com/compliance/business/payments/sepa-v4

class PaymentStatus:
    """Internal payment status values. Provider-specific values and mappings are defined in each provider's constants file."""
    PENDING_CONFIRMATION = 'pending_confirmation'   # Nordea API: A payment was created. Confirmation step has not yet been started.
    PENDING_USER_APPROVAL = 'pending_user_approval' # nORDEA api: The PSU-signing process has started.
    ON_HOLD = 'on_hold'
    CONFIRMED = 'confirmed'
    PARTIALLY_CONFIRMED = 'partially_confirmed'
    PROCESSING = 'processing'
    PROCESSED = 'processed'
    REJECTED = 'rejected'
    INSUFFICIENT_FUNDS = 'insufficient_funds'
    LIMIT_EXCEEDED = 'limit_exceeded'
    USER_APPROVAL_FAILED = 'user_approval_failed'
    USER_APPROVAL_TIMEOUT = 'user_approval_timeout'
    USER_APPROVAL_CANCELLED = 'user_approval_cancelled'
    PAID = 'paid'
    UNCONFIRMED = 'unconfirmed'
    UNKNOWN = 'unknown'
    UNRECOGNIZED = 'unrecognized'

    SELECTION = [
        (PENDING_CONFIRMATION, 'Pending Confirmation'),
        (PENDING_USER_APPROVAL, 'Pending User Approval'),
        (ON_HOLD, 'On Hold'),       # e.g. blocked in the AML (Anti-Money Laundering), user must contact Nordea to proceed
        (CONFIRMED, 'Confirmed'),
        (PARTIALLY_CONFIRMED, 'Partially Confirmed'),
        (PROCESSING, 'Processing'),
        (PROCESSED, 'Processed'),
        (REJECTED, 'Rejected'),
        (INSUFFICIENT_FUNDS, 'Insufficient Funds'),
        (LIMIT_EXCEEDED, 'Limit Exceeded'),
        (USER_APPROVAL_FAILED, 'User Approval Failed'),
        (USER_APPROVAL_TIMEOUT, 'User Approval Timed Out'),
        (USER_APPROVAL_CANCELLED, 'User Approval Cancelled'),
        (PAID, 'Paid'),
        (UNCONFIRMED, 'Unconfirmed'),
        (UNKNOWN, 'Unknown'),
        (UNRECOGNIZED, 'Unrecognized'), # default status if something goes wrong
    ]

    # payment polling stops when a status from this set returned
    TERMINAL = frozenset([
        # success
        PROCESSED,
        PAID,

        # require user action
        REJECTED,
        INSUFFICIENT_FUNDS,
        USER_APPROVAL_FAILED,
        USER_APPROVAL_TIMEOUT,
        USER_APPROVAL_CANCELLED,
    ])
    
class AccountPaymentState:
    """Values of the account.payment state field (Odoo 18)."""
    IN_PROCESS = 'in_process'
    PAID = 'paid'
    SENDABLE = frozenset([IN_PROCESS, PAID])
    
class SepaConstraints:
    """Limits shared across all SEPA providers."""
    MAX_NAME_LENGTH = 70       # OP and Nordea set the same limit so keeping it here for now
    SUPPORTED_CURRENCY = 'EUR'
    MAX_REFERENCE_LENGTH = 25        # Finnish structured reference (Viite / RF)

# Nordea Corporate Access only requires IDs to be unique within the last 90 calendar
# days, so a banking_payment_id may legitimately repeat later. Lookups by
# banking_payment_id only consider payments created within this window.
BANKING_ID_REUSE_WINDOW_DAYS = 90