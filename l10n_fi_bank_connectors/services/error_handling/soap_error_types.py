from .error_types import BankingError


class BankingProtocolError(BankingError):
    """A response was received, but its SOAP payload was malformed or unexpected."""


class BankingResponseCodeError(BankingError):
    """The bank answered with a failure code of its own application-level protocol.

    Covers the bank's response codes and SOAP fault codes.
    """

    def __init__(self, response_code: str, message: str):
        self.response_code = response_code
        self.message = message
        super().__init__(message)