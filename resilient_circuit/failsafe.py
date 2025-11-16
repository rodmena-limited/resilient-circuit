from typing import Callable, Sequence, TypeVar

from typing_extensions import ParamSpec

from resilient_circuit.policy import ProtectionPolicy

R = TypeVar("R")
P = ParamSpec("P")


class SafetyNet:
    """Decorates function with given policies.

    SafetyNet will handle execution results in reverse, with last policy applied first.

    Example:
        >>> from resilient_circuit import SafetyNet, RetryWithBackoffPolicy, CircuitProtectorPolicy
        >>>
        >>> @SafetyNet(policies=(RetryWithBackoffPolicy(), CircuitProtectorPolicy()))
        >>> def some_method() -> bool:
        >>>     return True
    """

    def __init__(self, *, policies: Sequence[ProtectionPolicy]) -> None:
        if len(policies) != len(set(policies)):
            raise ValueError("All policies must be unique.")

        self.policies = policies

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        """Decorate func with all policies in reversed order."""
        for policy in reversed(self.policies):
            func = policy(func)
        return func
