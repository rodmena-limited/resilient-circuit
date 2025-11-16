class ProtectionException(Exception):
    pass


class RetryLimitReached(ProtectionException):
    pass


class ProtectedCallError(ProtectionException):
    pass
