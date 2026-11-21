from ....base_banking_service import ProviderBackend

PROVIDER_NAME = 'Nordea Corporate Access'
FAMILY_KEY = 'nordea_corporate_access'
BACKENDS = ProviderBackend.make_pair(FAMILY_KEY, PROVIDER_NAME)
BACKEND_SANDBOX, BACKEND_PROD = BACKENDS