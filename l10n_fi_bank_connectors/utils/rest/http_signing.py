import base64
import hashlib

from ...utils.crypto import rsa_sign
from ...services.constants.crypto import RSA_SHA256


def build_http_signature(private_key, key_id: str, method: str, path: str, headers_to_sign: dict,) -> str:
    """
    Build a Nordea HTTP Message Signature header value per RFC draft cavage-http-signatures-10.
    headers_to_sign must contain all headers that should be included in the signature.
    For requests with body: X-Nordea-Originating-Host, X-Nordea-Originating-Date, Content-Type , Digest
    For requests without body: X-Nordea-Originating-Host, X-Nordea-Originating-Date
    """
    request_target = f"{method.lower()} {path}"

    components = [f"(request-target): {request_target}"]
    header_ids = ["(request-target)"]

    for name, value in headers_to_sign.items():
        components.append(f"{name.lower()}: {value}")
        header_ids.append(name.lower())

    signing_string = "\n".join(components)
    signature_bytes = rsa_sign(private_key, signing_string.encode("utf-8"))
    signature_b64 = base64.b64encode(signature_bytes).decode()

    headers_str = " ".join(header_ids)
    return (
        f'keyId="{key_id}",'
        f'algorithm="{RSA_SHA256}",'
        f'headers="{headers_str}",'
        f'signature="{signature_b64}"'
    )


def compute_sha256_digest(data: bytes) -> str:
    """
    Compute a SHA-256 digest string for Nordea API headers:'SHA-256=<base64-encoded-hash>' specified as follows:
    "The Digest Header header as defined in [RFC3230] contains a Hash of the message body. The only hash algorithms that may be used 
    to calculate the Digest within the context of this specification are SHA-256 and SHA-512 as defined in [RFC5843]. For POST with 
    'application/x-www-form-urlencoded' content type Digest should be calculated for normalized string created from request parameters 
    like this: 'param1=value1&param2=value2'. It is important that parameters should be placed in alphabetic order"
    see: https://developer.nordeaopenbanking.com/apiReference?api=Business%2520Access%2520Authorization%2520API&version=5
    """
    return "SHA-256=" + base64.b64encode(hashlib.sha256(data).digest()).decode()
