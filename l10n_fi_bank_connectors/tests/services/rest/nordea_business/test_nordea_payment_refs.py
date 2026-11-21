from odoo.tests.common import BaseCase

from .....utils.payment_refs import validate_rf_reference, validate_viitenumero

def generate_rf_reference(payment_id: int) -> str:
    """Generate a valid ISO 11649 RF Creditor Reference from a payment ID."""
    raw_ref = str(payment_id).zfill(19)
    converted = raw_ref + "271500"  # RF00
    check_digits = 98 - (int(converted) % 97)
    return f"RF{check_digits:02d}{raw_ref}"


class TestNordeaPaymentRefs(BaseCase):

    def test_validate_rf_reference_case_insensitive(self):
        ref = generate_rf_reference(999)
        self.assertTrue(validate_rf_reference(ref.lower()))

    def test_validate_rf_reference_wrong_prefix(self):
        self.assertFalse(validate_rf_reference("XX1234567890"))

    def test_validate_rf_reference_too_short(self):
        self.assertFalse(validate_rf_reference("RF1"))

    def test_validate_rf_reference_bad_checksum(self):
        ref = generate_rf_reference(12345)
        tampered = "RF00" + ref[4:]
        self.assertFalse(validate_rf_reference(tampered))

    def test_validate_rf_reference_invalid_character(self):
        self.assertFalse(validate_rf_reference("RF12 34*678"))

    def test_validate_viitenumero_wrong_check_digit(self):
        self.assertFalse(validate_viitenumero("12345670"))  # arbitrary wrong check digit

    def test_validate_viitenumero_non_digit(self):
        self.assertFalse(validate_viitenumero("12A4567"))

    def test_validate_viitenumero_too_short(self):
        self.assertFalse(validate_viitenumero("1"))

    def test_validate_viitenumero_strips_whitespace(self):
        body = "1234567"
        weights = [7, 3, 1]
        total = sum(int(d) * weights[i % 3] for i, d in enumerate(reversed(body)))
        remainder = total % 10
        check = 0 if remainder == 0 else 10 - remainder
        viitenumero = body + str(check)
        self.assertTrue(validate_viitenumero(f"  {viitenumero}  "))
