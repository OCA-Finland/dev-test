import uuid

def generate_unique_id() -> str:
    """
    Generate a unique instruction ID for OP Corporate payment requests.
    Format: 32 uppercase hex characters (UUID4, hyphens removed).
    See: https://op-developer.fi/products/banking/docs/op-corporate-payment-api#operation/payment
    """
    return uuid.uuid4().hex.upper()
