from enum import Enum

# Appendix A in https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
# Codes missing from the table (06, 09-11, 13, 16-17, 27-28, 32, 34) are not documented
# and are not defined here.


class NordeaResponseCode(str, Enum):
    """ApplicationResponse ResponseCode values, the value is the Appendix A code."""

    def __new__(cls, code: str, description: str):
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj.description = description
        return obj

    OK = ("00", "The request was processed successfully.")
    SOAP_SIGNATURE_ERROR_02 = ("02", "SOAP signature verification failed.")
    SOAP_SIGNATURE_ERROR_03 = ("03", "SOAP signature verification failed.")
    SOAP_SIGNATURE_ERROR_04 = ("04", "SOAP signature verification failed.")
    OPERATION_UNKNOWN = ("05", "The requested operation is unknown.")
    SENDER_ID_NOT_FOUND = ("07", "The sender ID is not registered with Nordea.")
    SENDER_ID_LOCKED = ("08", "The sender ID is locked by Nordea.")
    SCHEMA_VALIDATION_FAILED = ("12", "Nordea rejected the request because its XML schema is invalid.")
    CUSTOMER_ID_LOCKED = ("14", "The customer ID is locked.")
    CUSTOMER_ID_OUTDATED = ("15", "The customer ID is outdated.")
    CONTENT_SIGNATURE_INVALID = ("18", "The content digital signature is invalid.")
    CONTENT_CERTIFICATE_INVALID = ("19", "The signing certificate is invalid, expired, or revoked.")
    CONTENT_TYPE_INVALID = ("20", "The content does not match the declared file type.")
    DEFLATE_ERROR = ("21", "Nordea could not decompress the submitted content.")
    DECRYPT_ERROR = ("22", "Nordea could not decrypt the submitted content.")
    CONTENT_PROCESSING_ERROR = ("23", "Nordea could not process the submitted content.")
    CONTENT_NOT_FOUND = ("24", "The requested content was not found.")
    SIGNATURE_ALGORITHM_NOT_SUPPORTED = ("25", "The signature algorithm is not supported.")
    TECHNICAL_ERROR = ("26", "Nordea reported a technical error.")
    INVALID_PARAMETERS = ("29", "Nordea rejected an invalid request parameter.")
    AUTHENTICATION_FAILED = ("30", "Authentication failed: the sender or signer ID is unknown.")
    DUPLICATE_MESSAGE_REJECTED = ("31", "Nordea rejected a duplicate message ID.")
    CUSTOMER_INFORMATION_ERROR = ("33", "Nordea reported an error in the customer information.")
    AUTHORISATION_FAILED = ("35", "The signer is not authorized to submit this file type.")
    TECHNICAL_ERROR_CONTACT_HELPDESK = ("36", "Nordea reported a technical error. Contact the bank helpdesk.")
    TECHNICAL_ERROR_APPLICATION_REQUEST = ("37", "Nordea could not process the ApplicationRequest.")

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_code(cls, raw_code: str | None) -> "NordeaResponseCode | None":
        """Return the matching member, or None for a missing or undocumented code.

        The spec writes success as both "0" (section 4.4) and "00" (Appendix A),
        so single-digit numeric codes are zero-padded before the lookup.
        """
        code = (raw_code or "").strip()
        if code.isdigit():
            code = code.zfill(2)
        try:
            return cls(code)
        except ValueError:
            return None

# Nordea returns 24 / "Content not found" for the shared demo certificate user:
# there is no service overview to report, but the connection itself succeeded.
RESPONSE_CODES_OK_OR_NO_CONTENT = (
    NordeaResponseCode.OK,
    NordeaResponseCode.CONTENT_NOT_FOUND,
)