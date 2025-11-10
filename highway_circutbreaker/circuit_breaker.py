import abc
import enum
from datetime import datetime, timedelta
from fractions import Fraction
from functools import wraps
from typing import Callable, Optional, TypeVar

from typing_extensions import ParamSpec

from highway_circutbreaker.buffer import BoolCircularBuffer
from highway_circutbreaker.exceptions import CircuitBreakerOpenError
from highway_circutbreaker.policy import Policy

R = TypeVar("R")
P = ParamSpec("P")


class State(enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerPolicy(Policy):
    DEFAULT_THRESHOLD = Fraction(1, 1)

    def __init__(
        self,
        *,
        cooldown: timedelta = timedelta(0),
        failure_threshold: Fraction = DEFAULT_THRESHOLD,
        success_threshold: Fraction = DEFAULT_THRESHOLD,
        handle: Callable[[Exception], bool] = lambda e: True,
        on_state_change: Optional[
            Callable[["CircuitBreakerPolicy", State, State], None]
        ] = None,
    ) -> None:
        self.cooldown = cooldown
        self.success_threshold = success_threshold
        self.failure_threshold = failure_threshold
        self.can_handle = handle
        self._on_state_change = on_state_change
        self._state: BaseState = ClosedState(policy=self)

    @property
    def history(self) -> BoolCircularBuffer:
        return self._state.history

    @property
    def state(self) -> State:
        return self._state.type

    @state.setter
    def state(self, new_state: State) -> None:
        old_state = self.state
        if new_state is State.CLOSED:
            self._state = ClosedState(policy=self)
        elif new_state is State.OPEN:
            self._state = OpenState(policy=self, previous_state=self._state)
        else:
            self._state = HalfOpenState(policy=self)

        self.on_state_change(old_state, new_state)

    def on_state_change(self, current: State, new: State) -> None:
        """This method is called whenever breaker changes its state."""
        if self._on_state_change is not None:
            self._on_state_change(self, current, new)

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def decorated(*args: P.args, **kwargs: P.kwargs) -> R:
            self._state.guard_execution()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                if self.can_handle(e):
                    self._state.on_error()
                else:
                    self._state.on_success()
                raise
            else:
                self._state.on_success()
                return result

        return decorated


class BaseState(abc.ABC):
    """Interface describing common methods of CircuitBreaker's state."""

    history: BoolCircularBuffer

    def __init__(self, policy: CircuitBreakerPolicy):
        self.policy = policy

    @property
    @abc.abstractmethod
    def type(self) -> State:
        """Defines type of the state."""

    @abc.abstractmethod
    def guard_execution(self) -> None:
        """Override this method to raise an exception to prevent execution."""

    @abc.abstractmethod
    def on_error(self) -> None:
        """This method is called whenever execution fails."""

    @abc.abstractmethod
    def on_success(self) -> None:
        """This method is called whenever execution succeeds."""


class ClosedState(BaseState):
    type = State.CLOSED

    def __init__(self, policy: CircuitBreakerPolicy):
        super().__init__(policy)
        self.history = BoolCircularBuffer(size=policy.failure_threshold.denominator)

    def guard_execution(self) -> None:
        # In the CLOSED state, execution is allowed
        pass

    def on_error(self) -> None:
        self.history.add(False)
        if (
            self.history.is_full
            and self.history.failure_ratio >= self.policy.failure_threshold
        ):
            self.policy.state = State.OPEN

    def on_success(self) -> None:
        self.history.add(True)


class OpenState(BaseState):
    type = State.OPEN

    def __init__(self, policy: CircuitBreakerPolicy, previous_state: BaseState) -> None:
        super().__init__(policy)
        self.history = previous_state.history
        self.opened_at = datetime.now()

    def guard_execution(self) -> None:
        if datetime.now() - self.opened_at < self.policy.cooldown:
            raise CircuitBreakerOpenError

    def on_error(self) -> None:
        # In OPEN state, errors are not recorded because execution is blocked
        pass

    def on_success(self) -> None:
        self.policy.state = State.HALF_OPEN


class HalfOpenState(BaseState):
    type = State.HALF_OPEN

    def __init__(self, policy: CircuitBreakerPolicy):
        super().__init__(policy)
        self.use_success = policy.success_threshold != policy.DEFAULT_THRESHOLD
        self.history = BoolCircularBuffer(
            size=(
                policy.success_threshold.denominator
                if self.use_success
                else policy.failure_threshold.denominator
            )
        )

    def guard_execution(self) -> None:
        # In HALF_OPEN state, execution is allowed
        pass

    def on_error(self) -> None:
        self.history.add(False)
        self._check_threshold()

    def on_success(self) -> None:
        self.history.add(True)
        self._check_threshold()

    def _check_threshold(self) -> None:
        """Determine whether a threshold has been met and the circuit should be opened or closed.

        The circuit changes state only after the expected number of executions take place.
        If configured, success ratio has precedence over failure ratio.
        """

        if not self.history.is_full:
            return

        if self.use_success:
            self.policy.state = (
                State.CLOSED
                if self.history.success_ratio >= self.policy.success_threshold
                else State.OPEN
            )
        else:
            self.policy.state = (
                State.OPEN
                if self.history.failure_ratio >= self.policy.failure_threshold
                else State.CLOSED
            )
