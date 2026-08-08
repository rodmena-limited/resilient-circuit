import threading
from fractions import Fraction
from typing import Generic, Iterator, List, TypeVar

T = TypeVar("T")


class GenericCircularBuffer(Generic[T]):
    """Buffer that keeps last N items.

    Iteration and statistics are thread-safe against concurrent ``add``
    calls: reads observe a consistent snapshot.
    """

    def __init__(self, size: int) -> None:
        if size < 1:
            raise ValueError("`size` must be positive.")

        self.size = size
        self._items: List[T] = []
        self._lock = threading.RLock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __iter__(self) -> Iterator[T]:
        with self._lock:
            return iter(list(self._items))

    def __str__(self) -> str:
        with self._lock:
            return str(self._items)

    def __repr__(self) -> str:
        with self._lock:
            return f"<{self.__class__.__name__}(size={self.size}): {self._items}>"

    def add(self, item: T) -> None:
        with self._lock:
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
        with self._lock:
            return self._items.count(True)

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._items.count(False)

    @property
    def success_rate(self) -> Fraction:
        return Fraction(self.success_count, len(self))

    @property
    def failure_rate(self) -> Fraction:
        return Fraction(self.failure_count, len(self))
