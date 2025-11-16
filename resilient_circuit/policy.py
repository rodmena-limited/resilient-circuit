import abc
from typing import Callable, TypeVar

from typing_extensions import ParamSpec

R = TypeVar("R")
P = ParamSpec("P")


class ProtectionPolicy(abc.ABC):
    @abc.abstractmethod
    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        """Apply policy to callable."""
