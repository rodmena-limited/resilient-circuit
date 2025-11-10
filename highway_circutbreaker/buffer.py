from fractions import Fraction
from typing import Generic, List, TypeVar

T = TypeVar("T")


class GenericCircularBuffer(Generic[T]):
    """Buffer that keeps last N items."""

    def __init__(self, size: int) -> None:
        if size < 1:
            raise ValueError("`size` must be positive.")

        self.size = size
        self._items: List[T] = []

    def __len__(self) -> int:
        return len(self._items)

    def __str__(self) -> str:
        return str(self._items)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(size={self.size}): {self}>"

    def add(self, item: T) -> None:
        self._items.append(item)
        self._items = self._items[-self.size :]

    @property
    def is_full(self) -> bool:
        return len(self) >= self.size


class BinaryCircularBuffer(GenericCircularBuffer[bool]):
    """GenericCircularBuffer of boolean items.

    Introduces properties to get success/failures and their respective ratios.
    """

    @property
    def success_count(self) -> int:
        return self._items.count(True)

    @property
    def failure_count(self) -> int:
        return self._items.count(False)

    @property
    def success_rate(self) -> Fraction:
        return Fraction(self.success_count, len(self))

    @property
    def failure_rate(self) -> Fraction:
        return Fraction(self.failure_count, len(self))
