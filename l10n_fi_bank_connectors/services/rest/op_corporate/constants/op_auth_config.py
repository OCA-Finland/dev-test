from ....base_banking_service import ProviderBackend

PROVIDER_NAME = "OP Corporate"
FAMILY_KEY = "op_corporate"

BACKENDS = ProviderBackend.make_pair(FAMILY_KEY, PROVIDER_NAME)
BACKEND_SANDBOX, BACKEND_PROD = BACKENDS

TOKEN_DEFAULT_EXPIRY_SECONDS = 900