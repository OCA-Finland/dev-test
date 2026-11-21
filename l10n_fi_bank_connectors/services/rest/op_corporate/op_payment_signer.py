import base64
import json

from time import time

from ...constants.http import ENCODING_UTF8
from ....utils.crypto import load_rsa_private_key, rsa_sign


"""
Helper methods used in payment init flow. For details, see 
https://op-developer.fi/products/banking/docs/op-corporate-payment-api#operation/paymentV3
"""

def _b64url(data: bytes) -> str:
    """Base64url-encode bytes with no padding."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _build_jws_header(kid: str) -> dict:
    """Build the JWS protected header with mandatory fields for the OP API."""
    return {
        "alg": "RS256",
        "kid": kid,
        "b64": False,
        "urn:op.api.iat": int(time()),     # represents the number of seconds from 1970-01-01T0:0:0Z as measured in GMT until the date/time
        "crit": ["b64", "urn:op.api.iat"],
    }

def sign_request(payload: str, signing_key_pem: str, kid: str) -> str:
    """Build a JWS signature. Returns the value to set as the X-Req-Signature header: {base64url_header}..{base64url_signature}"""
    if not payload:
        raise ValueError("payload must not be empty.")
    if not signing_key_pem:
        raise ValueError("signing_key_pem must not be empty.")
    if not kid:
        raise ValueError("key id must not be empty.")
    
    header = _build_jws_header(kid)
    header_bytes = json.dumps(header, separators=(',', ':')).encode()
    encoded_header = _b64url(header_bytes)

    payload_bytes = payload.encode(ENCODING_UTF8)
    signing_input = f"{encoded_header}.".encode() + payload_bytes

    private_key = load_rsa_private_key(signing_key_pem)
    signature = rsa_sign(private_key, signing_input)
    encoded_signature = _b64url(signature)

    return f"{encoded_header}..{encoded_signature}"
