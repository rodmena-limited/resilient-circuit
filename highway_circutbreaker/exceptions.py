class FailsafeException(Exception):
    pass


class RetriesExceeded(FailsafeException):
    pass


class CircuitBreakerOpenError(FailsafeException):
    pass
