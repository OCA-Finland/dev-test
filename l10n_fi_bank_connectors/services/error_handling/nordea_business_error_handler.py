from .base_error_handler import RestErrorHandler

AUTH_ERROR_CODES = {400, 401, 403}

class NordeaBusinessErrorHandler(RestErrorHandler):
    """Error handler for Nordea Business API."""

    _auth_error_codes = frozenset(AUTH_ERROR_CODES)

    @property
    def _error_map(self) -> dict[int, str]:
        return {
            400: "{provider}: bad request. Check your configuration.",
            401: "{provider}: invalid credentials. Check that your Client ID and Client Secret are correct.",
            403: "{provider}: not authorized.",
            404: "{provider}: resource not found.",
        }
    
    def _extract_detail(self, body: dict) -> str:
        if not isinstance(body, dict):
            return ""
        error = body.get("error", {})
        if isinstance(error, dict):
            failures = error.get("failures", [])
            parts = []
            if isinstance(failures, list):
                for failure in failures:
                    if not isinstance(failure, dict):
                        continue
                    detail = failure.get("description") or failure.get("code")
                    if detail:
                        parts.append(str(detail))
            if parts:
                return "; ".join(parts)
        return ""