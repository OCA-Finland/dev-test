# odoo.conf
CONFIG_KEY = "banking_encryption_key"
SHOW_SANDBOX_CONFIG_KEY = "banking_show_sandbox_backends"

TOKEN_EXPIRY_BUFFER_SECONDS = 30
EXPIRY_WARN_DAYS = 7

# Backends that use user-consent OAuth2. An auth failure (HTTP 400/401) on
# these backends pauses the cron immediately without waiting for the
# consecutive-failure threshold, since retrying won't help until the user
# re-authorizes.
CONSENT_BASED_AUTH_FAMILIES: frozenset[str] = frozenset({
    'nordea_business',
})


# no DELETE status because when user deletes a connection in UI, Odoo automatically deletes the connection row in DB as well,
# incl. credentials, and online banking account data
class ConnectionStatus:
    """Status values for online.banking.connection."""
    PENDING = 'pending'
    ACTIVE = 'active'
    EXPIRED = 'expired'

    SELECTION = [
        (PENDING, 'Pending'),
        (ACTIVE, 'Active'),
        (EXPIRED, 'Expired'),
    ]


def cache_key(connection) -> tuple:
    """Key for auth-token/cert caches."""
    return (connection.api_backend, connection.id)