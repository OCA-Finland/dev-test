from decimal import Decimal

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ...services.constants.payments import SepaConstraints
from ...services.rest.nordea_business.nordea_dtos import NordeaPaymentRequestDTO
from ...services.rest.nordea_business.constants.nordea_payments import NordeaFIPaymentLimits
from ...services.rest.nordea_business.nordea_payment_validator import NordeaFIPaymentValidator
from ...services.rest.op_corporate.constants.op_payments import OPPaymentLimits
from ...services.rest.op_corporate.op_dtos import OPPaymentRequestDTO
from ...services.rest.op_corporate.op_payment_validator import OPPaymentValidator

def _op_dto(**overrides) -> OPPaymentRequestDTO:
    """OP payment DTO."""
    defaults = dict(
        creditor_name="Creditor Oy",
        creditor_iban="FI2112345600000785",
        debtor_name="Debtor Oy",
        debtor_iban="FI4212345600000786",
        amount=Decimal("100.00"),
        currency="EUR",
        reference="RF18539007547034",
        instruction_id="INSTR001",
    )
    defaults.update(overrides)
    return OPPaymentRequestDTO(**defaults)


def _nordea_dto(**overrides) -> NordeaPaymentRequestDTO:
    """Nordea payment DTO."""
    defaults = dict(
        creditor_name="Creditor Oy",
        creditor_iban="FI2112345600000785",
        debtor_name="Debtor Oy",
        debtor_iban="FI4212345600000786",
        amount=Decimal("100.00"),
        currency="EUR",
    )
    defaults.update(overrides)
    return NordeaPaymentRequestDTO(**defaults)


def _raises(validator_cls, dto):
    """Return the UserError, or fail if none raised."""
    try:
        validator_cls(dto).validate()
    except UserError as e:
        return e
    raise AssertionError("Expected UserError was not raised")


def _passes(validator_cls, dto):
    """Assert the validator raises no UserError."""
    validator_cls(dto).validate()

# shared checks, tested with OPPaymentValidator
class TestBaseValidatorCurrency(TransactionCase):

    def test_eur(self):
        """Test that EUR passes the check."""
        _passes(OPPaymentValidator, _op_dto(currency="EUR"))
    
    def test_lowercase_eur_fails(self):
        """Test that eur fails."""
        err = _raises(OPPaymentValidator, _op_dto(currency="eur"))
        self.assertIn("EUR", str(err))

    def test_non_eur(self):
        """Test that non-EUR fails."""
        err = _raises(OPPaymentValidator, _op_dto(currency="USD"))
        self.assertIn("EUR", str(err))


class TestBaseValidatorAmount(TransactionCase):

    def test_positive_amount(self):
        """Test that positive amount passes."""
        _passes(OPPaymentValidator, _op_dto(amount=Decimal("0.01")))

    def test_zero_amount(self):
        """Test that zero amount fails."""
        err = _raises(OPPaymentValidator, _op_dto(amount=Decimal("0.00")))
        self.assertIn("greater than zero", str(err))

    def test_negative_amount(self):
        """Test that negative amount fails."""
        err = _raises(OPPaymentValidator, _op_dto(amount=Decimal("-1.00")))
        self.assertIn("greater than zero", str(err))


class TestBaseValidatorIBAN(TransactionCase):

    def test_valid_fi_iban(self):
        """Test that FI IBAN passes."""
        _passes(OPPaymentValidator, _op_dto(creditor_iban="FI2112345600000785"))

    def test_empty_creditor_iban(self):
        """Test that empty creditor IBAN fails."""
        err = _raises(OPPaymentValidator, _op_dto(creditor_iban=""))
        self.assertIn("Creditor IBAN", str(err))

    def test_empty_debtor_iban(self):
        """Test that empty debtor IBAN fails."""
        err = _raises(OPPaymentValidator, _op_dto(debtor_iban=""))
        self.assertIn("Debtor IBAN", str(err))

    def test_invalid_iban_format(self):
        """Test that invalid IBAN fails."""
        err = _raises(OPPaymentValidator, _op_dto(creditor_iban="NOT-AN-IBAN"))
        self.assertIn("invalid IBAN", str(err))

    def test_iban_with_spaces(self):
        """Test that IBAN with spaces passes."""
        _passes(OPPaymentValidator, _op_dto(creditor_iban="FI21 1234 5600 0007 85"))

    def test_lowercase_iban(self):
        """Test that lowercase IBAN passes."""
        _passes(OPPaymentValidator, _op_dto(creditor_iban="fi2112345600000785"))


class TestBaseValidatorName(TransactionCase):

    def test_valid_name(self):
        """Test that valid creditor name passes."""
        _passes(OPPaymentValidator, _op_dto(creditor_name="Acme Oy"))

    def test_empty_creditor_name(self):
        """Test that empty creditor name fails."""
        err = _raises(OPPaymentValidator, _op_dto(creditor_name=""))
        self.assertIn("Creditor name", str(err))

    def test_empty_debtor_name(self):
        """Test that empty debtor name fails."""
        err = _raises(OPPaymentValidator, _op_dto(debtor_name=""))
        self.assertIn("Debtor name", str(err))

    def test_name_at_max_length(self):
        """Test that max length creditor name passes."""
        _passes(OPPaymentValidator, _op_dto(creditor_name="A" * SepaConstraints.MAX_NAME_LENGTH))

    def test_name_over_max_length(self):
        """Test that too long creditor name fails."""
        err = _raises(OPPaymentValidator, _op_dto(creditor_name="A" * (SepaConstraints.MAX_NAME_LENGTH + 1)))
        self.assertIn("Creditor name", str(err))
        self.assertIn("too long", str(err))


class TestBaseValidatorMultipleErrors(TransactionCase):

    def test_multiple_errors(self):
        """Test that all errors reported."""
        dto = _op_dto(currency="USD", creditor_iban="", debtor_name="")
        err = _raises(OPPaymentValidator, dto)
        msg = str(err)
        self.assertIn("EUR", msg)
        self.assertIn("Creditor IBAN", msg)
        self.assertIn("Debtor name", msg)


# OP validator
class TestOPValidatorInstructionId(TransactionCase):

    def test_valid_instruction_id(self):
        """Test that valid instruction id passes."""
        _passes(OPPaymentValidator, _op_dto(instruction_id="ABC123"))

    def test_empty_instruction_id(self):
        """Test that empty instruction id fails."""
        err = _raises(OPPaymentValidator, _op_dto(instruction_id=""))
        self.assertIn("Instruction ID", str(err))

    def test_instruction_id_max_length(self):
        """Test that max length instruction id passes."""
        _passes(OPPaymentValidator, _op_dto(instruction_id="A" * 35))

    def test_instruction_id_over_max_length(self):
        """Test that over max length instruction id fails."""
        err = _raises(OPPaymentValidator, _op_dto(instruction_id="A" * 36))
        self.assertIn("Instruction ID", str(err))

    def test_instruction_id_special_chars(self):
        """Test that instruction id with special characters fails."""
        err = _raises(OPPaymentValidator, _op_dto(instruction_id="INSTR-001"))
        self.assertIn("Instruction ID", str(err))

    def test_alphanumeric_instruction_id(self):
        """Test that instruction id with alphanumeric characters passes."""
        _passes(OPPaymentValidator, _op_dto(instruction_id="ABCDEF1234567890"))


class TestOPValidatorReference(TransactionCase):

    def test_valid_reference(self):
        """Test that valid reference passes."""
        _passes(OPPaymentValidator, _op_dto(reference="RF18539007547034"))

    def test_empty_reference_with_message(self):
        """Test that empty reference with message passes."""
        _passes(OPPaymentValidator, _op_dto(reference="", message="Invoice 123"))

    def test_reference_max_length(self):
        """Test that max length reference passes."""
        _passes(OPPaymentValidator, _op_dto(reference="R" * OPPaymentLimits.MAX_REFERENCE_LENGTH))

    def test_reference_over_max_length(self):
        """Test that over max length reference fails."""
        err = _raises(OPPaymentValidator, _op_dto(reference="R" * (OPPaymentLimits.MAX_REFERENCE_LENGTH + 1)))
        self.assertIn("Reference", str(err))
        self.assertIn("maximum length", str(err))


class TestOPValidatorMessage(TransactionCase):

    def test_valid_message(self):
        """Test that valid message passes."""
        _passes(OPPaymentValidator, _op_dto(message="Invoice 123"))

    def test_message_at_max_length(self):
        """Test that max length message passes."""
        _passes(OPPaymentValidator, _op_dto(reference="", message="M" * OPPaymentLimits.MAX_MESSAGE_LENGTH))

    def test_message_over_max_length(self):
        """Test that over max length message fails."""
        err = _raises(OPPaymentValidator, _op_dto(reference="", message="M" * (OPPaymentLimits.MAX_MESSAGE_LENGTH + 1)))
        self.assertIn("Message", str(err))
        self.assertIn("maximum length", str(err))


class TestOPValidatorReferenceOrMessage(TransactionCase):
    """OP Corporate API requires the reference or the the message, or both to be present."""

    def test_reference_only(self):
        """Test that reference only passes."""
        _passes(OPPaymentValidator, _op_dto(reference="RF18539007547034", message=""))

    def test_message_only(self):
        """Test that message only passes."""
        _passes(OPPaymentValidator, _op_dto(reference="", message="Invoice 123"))

    def test_message_and_reference(self):
        """Test that message and reference passes."""
        _passes(OPPaymentValidator, _op_dto(reference="RF18539007547034", message="Invoice 123"))

    def test_empty_message_and_reference(self):
        """Test that empty message and empty reference fails."""
        err = _raises(OPPaymentValidator, _op_dto(reference="", message=""))
        self.assertIn("reference or a message", str(err))

    def test_whitespace_message_and_reference(self):
        """Test that empty space message and empty space reference fails."""
        err = _raises(OPPaymentValidator, _op_dto(reference="   ", message="   "))
        self.assertIn("reference or a message", str(err))


# Nordea validator
class TestNordeaValidatorCreditorMessage(TransactionCase):

    def test_no_message(self):
        """Test that no message passes."""
        _passes(NordeaFIPaymentValidator, _nordea_dto())

    def test_valid_message(self):
        """Test that valid message passes."""
        _passes(NordeaFIPaymentValidator, _nordea_dto(message="Invoice 123"))

    def test_message_at_max_length(self):
        """Test that max length message passes."""
        _passes(NordeaFIPaymentValidator, _nordea_dto(message="M" * NordeaFIPaymentLimits.MAX_CREDITOR_MESSAGE_LENGTH))

    def test_message_over_max_length(self):
        """Test that over max length message fails."""
        err = _raises(NordeaFIPaymentValidator, _nordea_dto(message="M" * (NordeaFIPaymentLimits.MAX_CREDITOR_MESSAGE_LENGTH + 1)))
        self.assertIn("Creditor message", str(err))
        self.assertIn("maximum length", str(err))


class TestNordeaValidatorRFReference(TransactionCase):

    def test_no_reference(self):
        """Test that no reference passes."""
        _passes(NordeaFIPaymentValidator, _nordea_dto())

    def test_non_rf_reference(self):
        """Test that plain Finnish viitenumero reference passes."""
        _passes(NordeaFIPaymentValidator, _nordea_dto(reference="1234561"))

    def test_valid_rf_reference(self):
        """Test that RF reference passes."""
        _passes(NordeaFIPaymentValidator, _nordea_dto(reference="RF18539007547034"))

    def test_invalid_rf_reference_fails(self):
        """Test that invalid RF reference fails."""
        err = _raises(NordeaFIPaymentValidator, _nordea_dto(reference="RF00"))
        self.assertIn("RF reference", str(err))
        self.assertIn("invalid format", str(err))

    def test_rf_prefix_case_insensitive(self):
        """Test that lowercase rf reference still triggers the RF format check."""
        err = _raises(NordeaFIPaymentValidator, _nordea_dto(reference="rf00"))
        self.assertIn("RF reference", str(err))

    def test_rf_reference_at_max_length(self):
        """Test that RF + 2 check digits + 21 alphanumeric = 25 chars total passes."""
        _passes(NordeaFIPaymentValidator, _nordea_dto(reference="RF18" + "A" * 21))


class TestNordeaValidatorAmountFormat(TransactionCase):

    def test_amount_within_nordea_limit(self):
        """Test that up to 9 digits amount passes."""
        _passes(NordeaFIPaymentValidator, _nordea_dto(amount=Decimal("999999999.99")))

    def test_amount_exceeding_nordea_limit_fails(self):
        """Test that 10 digits amount fails."""
        err = _raises(NordeaFIPaymentValidator, _nordea_dto(amount=Decimal("9999999999.99")))
        self.assertIn("amount", str(err).lower())
