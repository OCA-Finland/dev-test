class CronPauseReason:
    AUTH_ERROR = 'auth_error'
    CONSECUTIVE_FAILURES = 'consecutive_failures'
    
    SELECTION = [
        (AUTH_ERROR, 'Authorization error'),
        (CONSECUTIVE_FAILURES, 'Consecutive failures'),
    ]
    
    _VALID = {key for key, _ in SELECTION}
    
    @classmethod
    def validate(cls, reason:str):
        if reason not in cls._VALID:
            raise ValueError(
                "Invalid cron pause reason: %r. Must be: %s"
                % (reason, sorted(cls._VALID))
            )

CRON_FAILURE_THRESHOLD = 3      # how many times is cron allowed to fail consecutively
