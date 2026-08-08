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
        if self.factor < 1:
            raise ValueError("`factor` must be >= 1.")
        if self.max_delay < self.min_delay:
            raise ValueError("`max_delay` must be >= `min_delay`.")

    def for_attempt(self, attempt: int) -> float:
        """Compute delay in seconds for a given attempt.

        The delay never exceeds ``max_delay`` — the growth is capped at each
        step, so large attempts cannot overflow — and, once jitter is applied,
        never falls below ``min_delay``.
        """

        if attempt < 1:
            raise ValueError("`attempt` must be positive.")

        base = self.min_delay.total_seconds()
        cap = self.max_delay.total_seconds()
        factor = float(self.factor)

        delay = base
        for _ in range(1, attempt):
            delay = min(delay * factor, cap)
            if delay == cap:
                break

        if self.jitter is not None:
            offset = delay * self.jitter
            delay += random.uniform(-offset, offset)

        return max(base, min(delay, cap))


class FixedDelay(ExponentialDelay):
    """Special case of ExponentialDelay when delay between calls is constant."""

    def __init__(self, delay: timedelta) -> None:
        super().__init__(min_delay=delay, max_delay=delay, factor=1)
