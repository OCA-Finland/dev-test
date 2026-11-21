from abc import ABC, abstractmethod

from ..auth.token_cache import get_valid_token as _get, cache_token
from ..constants.connection import cache_key


class BaseAuth(ABC):
    """Abstract base for provider auth classes."""

    def __init__(self, connection):
        if not connection:
            raise ValueError("BaseAuth requires a connection record.")
        self.connection = connection
        self._cache_key = cache_key(connection)
    
    def get_valid_token(self) -> str:
        """Return a valid access token, fetching a new one if needed."""
        return _get(self._cache_key, self._fetch_or_refresh_access_token)

    def _cache_token(self, token: str, expires_in: int):
        """Store a token in the shared cache."""
        cache_token(self._cache_key, token, expires_in)

    @abstractmethod
    def _fetch_or_refresh_access_token(self) -> str:
        """Acquire a new token. Called when cache is empty or expired."""
        pass
