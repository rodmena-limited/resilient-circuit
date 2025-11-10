import abc
import enum
from datetime import datetime, timedelta
from fractions import Fraction
from functools import wraps
from typing import Callable, Optional, TypeVar

from typing_extensions import ParamSpec

from highway_circutbreaker.buffer import BinaryCircularBuffer
from highway_circutbreaker.exceptions import ProtectedCallError
from highway_circutbreaker.policy import ProtectionPolicy

R = TypeVar("R")
P = ParamSpec("P")


class CircuitStatus(enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitProtectorPolicy(ProtectionPolicy):
    DEFAULT_THRESHOLD = Fraction(1, 1)

    def __init__(
        self,
        *,
        cooldown: timedelta = timedelta(0),
        failure_limit: Fraction = DEFAULT_THRESHOLD,
        success_limit: Fraction = DEFAULT_THRESHOLD,
        should_handle: Callable[[Exception], bool] = lambda e: True,
        on_status_change: Optional[
            Callable[["CircuitProtectorPolicy", CircuitStatus, CircuitStatus], None]
        ] = None,
    ) -> None:
        self.cooldown = cooldown
        self.success_limit = success_limit
        self.failure_limit = failure_limit
        self.should_consider_failure = should_handle
        self._on_status_change = on_status_change
        self._status: CircuitStatusBase = StatusClosed(policy=self)

    @property
    def execution_log(self) -> BinaryCircularBuffer:
        return self._status.execution_log

    @property
    def status(self) -> CircuitStatus:
        return self._status.status_type

    @status.setter
    def status(self, new_status: CircuitStatus) -> None:
        old_status = self.status
        if new_status is CircuitStatus.CLOSED:
            self._status = StatusClosed(policy=self)
        elif new_status is CircuitStatus.OPEN:
            self._status = StatusOpen(policy=self, previous_status=self._status)
        else:
            self._status = StatusHalfOpen(policy=self)

        self.on_status_change(old_status, new_status)

    def on_status_change(self, current: CircuitStatus, new: CircuitStatus) -> None:
        """This method is called whenever protector changes its status."""
        if self._on_status_change is not None:
            self._on_status_change(self, current, new)

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def decorated(*args: P.args, **kwargs: P.kwargs) -> R:
            self._status.validate_execution()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                if self.should_consider_failure(e):
                    self._status.mark_failure()
                else:
                    self._status.mark_success()
                raise
            else:
                self._status.mark_success()
                return result

        return decorated


class CircuitStatusBase(abc.ABC):
    """Interface describing common methods of CircuitProtector's status."""

    execution_log: BinaryCircularBuffer

    def __init__(self, policy: CircuitProtectorPolicy):
        self.policy = policy

    @property
    @abc.abstractmethod
    def status_type(self) -> CircuitStatus:
        """Defines type of the status."""

    @abc.abstractmethod
    def validate_execution(self) -> None:
        """Override this method to raise an exception to prevent execution."""

    @abc.abstractmethod
    def mark_failure(self) -> None:
        """This method is called whenever execution fails."""

    @abc.abstractmethod
    def mark_success(self) -> None:
        """This method is called whenever execution succeeds."""


class StatusClosed(CircuitStatusBase):
    status_type = CircuitStatus.CLOSED

    def __init__(self, policy: CircuitProtectorPolicy):
        super().__init__(policy)
        self.execution_log = BinaryCircularBuffer(size=policy.failure_limit.denominator)

    def validate_execution(self) -> None:
        # In the CLOSED status, execution is allowed
        pass

    def mark_failure(self) -> None:
        self.execution_log.add(False)
        if (
            self.execution_log.is_full
            and self.execution_log.failure_rate >= self.policy.failure_limit
        ):
            self.policy.status = CircuitStatus.OPEN

    def mark_success(self) -> None:
        self.execution_log.add(True)


class StatusOpen(CircuitStatusBase):
    status_type = CircuitStatus.OPEN

    def __init__(self, policy: CircuitProtectorPolicy, previous_status: CircuitStatusBase) -> None:
        super().__init__(policy)
        self.execution_log = previous_status.execution_log
        self.transitioned_at = datetime.now()

    def validate_execution(self) -> None:
        if datetime.now() - self.transitioned_at < self.policy.cooldown:
            raise ProtectedCallError

    def mark_failure(self) -> None:
        # In OPEN status, errors are not recorded because execution is blocked
        pass

    def mark_success(self) -> None:
        self.policy.status = CircuitStatus.HALF_OPEN


class StatusHalfOpen(CircuitStatusBase):
    status_type = CircuitStatus.HALF_OPEN

    def __init__(self, policy: CircuitProtectorPolicy):
        super().__init__(policy)
        self.use_success = policy.success_limit != policy.DEFAULT_THRESHOLD
        self.execution_log = BinaryCircularBuffer(
            size=(
                policy.success_limit.denominator
                if self.use_success
                else policy.failure_limit.denominator
            )
        )

    def validate_execution(self) -> None:
        # In HALF_OPEN status, execution is allowed
        pass

    def mark_failure(self) -> None:
        self.execution_log.add(False)
        self._check_limit()

    def mark_success(self) -> None:
        self.execution_log.add(True)
        self._check_limit()

    def _check_limit(self) -> None:
        """Determine whether a limit has been met and the circuit should be opened or closed.

        The circuit changes status only after the expected number of executions take place.
        If configured, success ratio has precedence over failure ratio.
        """

        if not self.execution_log.is_full:
            return

        if self.use_success:
            self.policy.status = (
                CircuitStatus.CLOSED
                if self.execution_log.success_rate >= self.policy.success_limit
                else CircuitStatus.OPEN
            )
        else:
            self.policy.status = (
                CircuitStatus.OPEN
                if self.execution_log.failure_rate >= self.policy.failure_limit
                else CircuitStatus.CLOSED
            )
