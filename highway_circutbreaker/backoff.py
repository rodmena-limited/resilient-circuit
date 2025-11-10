import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional


@dataclass(frozen=True)
class ExponentialDelay:
    min_delay: timedelta
    max_delay: timedelta
    factor: int = 2
    jitter: Optional[float] = None

    def __post_init__(self) -> None:
        if self.jitter is not None and (self.jitter < 0 or self.jitter > 1):
            raise ValueError("`jitter` must be in range [0, 1].")

    def for_attempt(self, attempt: int) -> float:
        """Compute delay in seconds for a given attempt."""

        if attempt < 1:
            raise ValueError("`attempt` must be positive.")

        delay = self.min_delay.total_seconds() * pow(self.factor, attempt - 1)

        if self.jitter is not None:
            offset = delay * self.jitter
            delay += random.uniform(-offset, offset)

        return min(delay, self.max_delay.total_seconds())


class FixedDelay(ExponentialDelay):
    """Special case of ExponentialDelay when delay between calls is constant."""

    def __init__(self, delay: timedelta) -> None:
        super().__init__(min_delay=delay, max_delay=delay, factor=1)
