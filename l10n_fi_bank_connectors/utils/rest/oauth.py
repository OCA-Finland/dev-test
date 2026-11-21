import secrets
import urllib.parse


def generate_state() -> str:
    """Generate a random OAuth state value for Nordea authorization."""
    return secrets.token_hex(16)

def encode_params_alphabetically(params: dict) -> str:
    """URL-encode a dict of parameters with keys in alphabetical order."""
    parts = []
    for key, value in sorted(params.items()):
        encoded_key = urllib.parse.quote(str(key))
        encoded_value = urllib.parse.quote(str(value), safe='=')
        parts.append(f"{encoded_key}={encoded_value}")
    return "&".join(parts)