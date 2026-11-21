from .error_types import BankingAPIError


class BankingTokenError(BankingAPIError):
    """A non-2xx response to a token request, used in ErrorHandler.is_auth_error()."""