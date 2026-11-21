
def validate_rf_reference(ref: str) -> bool:
    """Validate an ISO 11649 RF Creditor Reference."""
    ref = ref.upper()
    if len(ref) < 5 or not ref.startswith("RF"):
        return False
    rearranged = ref[4:] + ref[:4]
    numeric_str = ""
    for ch in rearranged:
        if ch.isalpha():
            numeric_str += str(ord(ch) - ord('A') + 10)
        elif ch.isdigit():
            numeric_str += ch
        else:
            return False
    return int(numeric_str) % 97 == 1

def validate_viitenumero(ref: str) -> bool:
    """Validate a Finnish viitenumero check digit."""
    normalized = ref.strip()
    if not normalized.isdigit() or not (3 <= len(normalized) <= 20):
        return False
    weights = [7, 3, 1]
    body = normalized[:-1]
    check = int(normalized[-1])
    total = sum(int(d) * weights[i % 3] for i, d in enumerate(reversed(body)))
    remainder = total % 10
    expected = 0 if remainder == 0 else 10 - remainder
    return check == expected

def viitenumero_to_rf(ref: str) -> str:
    """Convert a viitenumero to ISO 11649 RF."""
    raw_ref = ref.strip().zfill(19)
    check_digits = 98 - (int(raw_ref + "271500") % 97)
    return f"RF{check_digits:02d}{raw_ref}"