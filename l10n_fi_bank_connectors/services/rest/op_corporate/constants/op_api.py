SANDBOX_BASE = "https://api.sandbox.corporate-api.op.fi"
PROD_BASE = "https://api.corporate-api.op.fi"

TOKEN_PATH = "/corporate-oidc/v1/token"
SANDBOX_TOKEN_URL = SANDBOX_BASE + TOKEN_PATH
PROD_TOKEN_URL = PROD_BASE + TOKEN_PATH

ACCOUNTS_PATH = "/corporate-account-data/v1/accounts"
ACCOUNT_DETAILS_PATH = "/corporate-account-data/v1/accounts/{surrogate_id}"
TRANSACTIONS_PATH = "/corporate-account-data/v3/accounts/{surrogate_id}/transactions"

PAYMENT_PATH = "/corporate-payment/v3/payment"
# OP API payment status path requires an instruction id (generated when a payment is initialized), 
# but we are storing instruction ids in the banking_payment_id column (= stores any ids 
# that APIs require for payment status queries)
PAYMENT_STATUS_PATH = "/corporate-payment/v3/payment/{banking_payment_id}"

# OP API allows: 50, 100, 150, 500 and 1000
PAGE_SIZE = 50
TRANSACTION_MAX_PAGES = 5

TRANSACTION_HISTORY_LIMIT_DAYS = 730 # approximation of 24 months specified in the docs
TRANSACTION_LOOKBACK_DAYS = 7   # we need to fetch also previous days, because 
                                # if the payment date falls on a non-banking day, the booking date is adjusted to be the next banking day

# HTTP
HEADER_OP_SIGNATURE = 'X-Req-Signature'