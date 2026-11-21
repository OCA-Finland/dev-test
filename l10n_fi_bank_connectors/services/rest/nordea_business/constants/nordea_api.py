
# Both sandbox and production use the same base URL. 
# The sandbox is distinguished by the X-Nordea-Sandbox-Authorizer-Id header.
BASE_URL = 'https://api.nordeaopenbanking.com'

# Nordea endpoint parameters
X_NORDEA_HOST = "api.nordeaopenbanking.com"
SANDBOX_SIGNATURE = "SKIP_SIGNATURE_VALIDATION_FOR_SANDBOX"
AUTH_TOKEN_PATH = "/business/v5/authorize/token"

AUTH_AUTHORIZE_URL = f"{BASE_URL}/business/v5/authorize"        # Initiation of the authentication and authorisation flow
AUTH_TOKEN_URL = f"{BASE_URL}{AUTH_TOKEN_PATH}"                 # The authorisation code exchange for an access token (and refresh token)

# Placeholder redirect URI shown in the OAuth wizard help text
EXAMPLE_REDIRECT_URI = "https://your-redirect-uri.com/callback"

PAYMENTS_SEPA_PATH = "/business/v4/payments/sepa"
PAYMENTS_CONFIRM_PATH = "/business/v4/payments/sepa/confirm"
PAYMENTS_STATUS_PATH = "/business/v4/payments/sepa/{payment_id}"

ACCOUNTS_PATH = "/business/v4/accounts"
TRANSACTIONS_PATH = "/business/v4/accounts/{account_id}/transactions"

# For Business Accounts APIs - maximum transaction history is up to 18 months, by default it's 2 months, 
# if max_tx_history parameter is not provided which is set during the user consent. 
# It can be further refined by from_date and to_date parameters. 
# Result will be returned in 200 transactions per page.
# https://support.nordeaopenbanking.com/hc/en-us/articles/7767693814044-Retrieving-Maximum-Transaction-History
TRANSACTION_HISTORY_LIMIT_DAYS = 547 # approximation
TRANSACTION_LOOKBACK_DAYS = 7        # use to make sure we pull all billed transactions


# Max message length for the creditor to appear on their transaction.
# https://developer.nordeaopenbanking.com/apiReference?api=Business%2520Payments%2520API%2520SEPA%2520Credit%2520Transfer&version=4
FI_SEPA_MAX_MESSAGE_LENGTH = 140

# Sandbox test authorizer IDs.
SANDBOX_PSU_FI = "29187251"

# Scopes required for AIS + PIS that should be included in /authorize
SCOPE_ACCOUNTS_BASIC = "ACCOUNTS_BASIC"
SCOPE_ACCOUNTS_BALANCES = "ACCOUNTS_BALANCES"
SCOPE_ACCOUNTS_DETAILS = "ACCOUNTS_DETAILS"
SCOPE_ACCOUNTS_TRANSACTIONS = "ACCOUNTS_TRANSACTIONS"
SCOPE_PAYMENTS_MULTIPLE = "PAYMENTS_MULTIPLE"

# HTTP
HEADER_DIGEST = 'Digest'
HEADER_IBM_CLIENT_ID = 'X-IBM-Client-Id'
HEADER_NORDEA_DATE = 'X-Nordea-Originating-Date'
HEADER_NORDEA_HOST = 'X-Nordea-Originating-Host'
HEADER_IBM_CLIENT_SECRET = 'X-IBM-Client-Secret'
HEADER_NORDEA_SANDBOX_AUTHORIZER_ID = 'X-Nordea-Sandbox-Authorizer-Id'
