from typing import Callable, Sequence, TypeVar

from typing_extensions import ParamSpec

from highway_circutbreaker.policy import Policy

R = TypeVar("R")
P = ParamSpec("P")


class Failsafe:
    """Decorates function with given policies.

    Failsafe will handle execution results in reverse, with last policy applied first.

    Example:
        >>> from highway_circutbreaker import Failsafe, RetryPolicy, CircuitBreakerPolicy
        >>>
        >>> @Failsafe(policies=(RetryPolicy(), CircuitBreakerPolicy()))
        >>> def some_method() -> bool:
        >>>     return True
    """

    def __init__(self, *, policies: Sequence[Policy]) -> None:
        if len(policies) != len(set(policies)):
            raise ValueError("All policies must be unique.")

        self.policies = policies

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        """Decorate func with all policies in reversed order."""
        for policy in reversed(self.policies):
            func = policy(func)
        return func
