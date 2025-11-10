from functools import wraps
from time import sleep
from typing import Callable, Optional, TypeVar

from typing_extensions import ParamSpec

from highway_circutbreaker.backoff import ExponentialDelay
from highway_circutbreaker.exceptions import RetryLimitReached
from highway_circutbreaker.policy import ProtectionPolicy

R = TypeVar("R")
P = ParamSpec("P")


class RetryWithBackoffPolicy(ProtectionPolicy):
    def __init__(
        self,
        *,
        backoff: Optional[ExponentialDelay] = None,
        max_retries: int = 3,
        should_handle: Callable[[Exception], bool] = lambda e: True,
    ):
        self.max_attempts = max_retries + 1
        self.backoff = backoff
        self.should_consider_failure = should_handle

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def decorated(*args: P.args, **kwargs: P.kwargs) -> R:
            attempt = 0
            last_exception = None

            while attempt < self.max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:  # pylint: disable=broad-except
                    if not self.should_consider_failure(e):
                        raise
                    last_exception = e

                attempt += 1
                if self.backoff:
                    sleep(self.backoff.for_attempt(attempt))

            raise RetryLimitReached from last_exception

        return decorated
