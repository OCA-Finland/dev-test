class CredentialType:
    """Credential type keys for online.banking.credential."""
    # --- OAuth2 (HTTP) ---
    CLIENT_ID = 'client_id'
    CLIENT_SECRET = 'client_secret'
    REFRESH_TOKEN = 'refresh_token'

    # --- OP Corporate ---
    OP_MTLS_CERT_PEM = 'op_mtls_cert_pem'
    OP_MTLS_KEY_PEM = 'op_mtls_key_pem'
    OP_PAYMENT_SIGNING_KEY = 'op_payment_signing_key'
    OP_PAYMENT_SIGNING_KID = 'op_payment_signing_kid'

    # --- Nordea Business ---
    NORDEA_AUTH_SIGNING_KEY = 'nordea_auth_signing_key'

    # --- Nordea Corporate Access ---
    NORDEA_CA_CERT_PEM = 'nordea_ca_cert_pem'
    NORDEA_CA_KEY_PEM = 'nordea_ca_key_pem'
    NORDEA_CA_SIGNER_ID = 'nordea_ca_signer_id'
    NORDEA_CA_SENDER_ID = 'nordea_ca_sender_id'


    SELECTION = [
        (CLIENT_ID, 'Client ID'),
        (CLIENT_SECRET, 'Client Secret'),
        (REFRESH_TOKEN, 'OAuth2 Refresh Token'),
        (OP_MTLS_CERT_PEM, 'OP mTLS Certificate (PEM)'),
        (OP_MTLS_KEY_PEM, 'OP mTLS Private Key (PEM)'),
        (OP_PAYMENT_SIGNING_KEY, 'OP Payment Signing Key (PEM)'),
        (OP_PAYMENT_SIGNING_KID, 'OP Payment Signing KID'),
        (NORDEA_AUTH_SIGNING_KEY, 'Nordea API Auth Signing Key (PEM)'),
        (NORDEA_CA_CERT_PEM, 'Nordea Corporate Access Certificate (PEM)'),
        (NORDEA_CA_KEY_PEM, 'Nordea Corporate Access Private Key (PEM)'),
        (NORDEA_CA_SIGNER_ID, 'Nordea Corporate Access Signer ID'),
        (NORDEA_CA_SENDER_ID, 'Nordea Corporate Access Sender ID'),
    ]

    LABELS = {k: v for k, v in SELECTION}
    
    # Require PEM validation
    PEM_TYPES = {
        OP_MTLS_CERT_PEM,
        OP_MTLS_KEY_PEM,
        OP_PAYMENT_SIGNING_KEY,
        NORDEA_AUTH_SIGNING_KEY,
        NORDEA_CA_CERT_PEM,
        NORDEA_CA_KEY_PEM,
    }

    # Types requiring RSA private key validation
    SIGNING_KEY_TYPES = {
        OP_PAYMENT_SIGNING_KEY,
        NORDEA_AUTH_SIGNING_KEY,
        OP_MTLS_KEY_PEM,
        NORDEA_CA_KEY_PEM,
    }

    # Require X.509 certificate validation
    CERT_TYPES = {
        OP_MTLS_CERT_PEM,
        NORDEA_CA_CERT_PEM,
    }

    # Store expiry dates in the db
    HAS_EXPIRY = {
        OP_MTLS_CERT_PEM,
        REFRESH_TOKEN,
        NORDEA_CA_CERT_PEM,
    }