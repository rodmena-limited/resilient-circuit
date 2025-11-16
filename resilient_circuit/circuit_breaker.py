import abc
import enum
import logging
from datetime import datetime, timedelta
from fractions import Fraction
from functools import wraps
from typing import Callable, Optional, TypeVar

from typing_extensions import ParamSpec

from resilient_circuit.buffer import BinaryCircularBuffer
from resilient_circuit.exceptions import ProtectedCallError
from resilient_circuit.policy import ProtectionPolicy
from resilient_circuit.storage import CircuitBreakerStorage, InMemoryStorage, create_storage

R = TypeVar("R")
P = ParamSpec("P")

logger = logging.getLogger(__name__)


class CircuitStatus(enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitProtectorPolicy(ProtectionPolicy):
    DEFAULT_THRESHOLD = Fraction(1, 1)

    def __init__(
        self,
        *,
        resource_key: Optional[str] = None,
        storage: Optional[CircuitBreakerStorage] = None,
        cooldown: timedelta = timedelta(0),
        failure_limit: Fraction = DEFAULT_THRESHOLD,
        success_limit: Fraction = DEFAULT_THRESHOLD,
        should_handle: Callable[[Exception], bool] = lambda e: True,
        on_status_change: Optional[
            Callable[["CircuitProtectorPolicy", CircuitStatus, CircuitStatus], None]
        ] = None,
    ) -> None:
        # Generate a default resource key if not provided for backward compatibility
        self.resource_key = resource_key or f"anonymous_{id(self)}"
        self.storage = storage or create_storage()
        self.cooldown = cooldown
        self.success_limit = success_limit
        self.failure_limit = failure_limit
        self.should_consider_failure = should_handle
        self._on_status_change = on_status_change

        # Load state from storage
        self._load_state()

    def _load_state(self) -> None:
        """Load circuit breaker state from storage."""
        try:
            state_data = self.storage.get_state(self.resource_key)
            if state_data:
                # Restore state from storage
                state = CircuitStatus(state_data["state"])
                failure_count = state_data.get("failure_count", 0)
                open_until = state_data.get("open_until", 0)

                # Initialize status based on stored state
                if state == CircuitStatus.CLOSED:
                    self._status = StatusClosed(policy=self, failure_count=failure_count)
                elif state == CircuitStatus.OPEN:
                    # For OPEN state, we need a previous status to pass to the constructor
                    # We'll use a temporary closed status with same failure count
                    temp_status = StatusClosed(policy=self, failure_count=failure_count)
                    self._status = StatusOpen(policy=self, previous_status=temp_status, open_until=open_until)
                else:  # HALF_OPEN
                    self._status = StatusHalfOpen(policy=self, failure_count=failure_count)

                logger.debug(f"Loaded circuit breaker state for {self.resource_key}: {state.value}")
            else:
                # No state found, start with CLOSED
                self._status = StatusClosed(policy=self)
                logger.debug(f"No stored state found for {self.resource_key}, starting with CLOSED")
        except Exception as e:
            logger.error(f"Failed to load state for {self.resource_key}: {e}")
            # Fallback to default state
            self._status = StatusClosed(policy=self)

    def _save_state(self) -> None:
        """Save circuit breaker state to storage."""
        try:
            state_data = {
                "state": self._status.status_type.value,
                "failure_count": getattr(self._status, 'failure_count', 0),
                # For StatusOpen, use open_until_timestamp; for others, default to 0
                "open_until": getattr(self._status, 'open_until_timestamp', 0) if hasattr(self._status, 'open_until_timestamp') else 0
            }

            self.storage.set_state(
                self.resource_key,
                state_data["state"],
                state_data["failure_count"],
                state_data["open_until"]
            )
            logger.debug(f"Saved circuit breaker state for {self.resource_key}: {state_data['state']}")
        except Exception as e:
            logger.error(f"Failed to save state for {self.resource_key}: {e}")

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
            # When transitioning to CLOSED, reset failure count
            self._status = StatusClosed(policy=self, failure_count=0)
        elif new_status is CircuitStatus.OPEN:
            # When transitioning to OPEN, keep the failure count from current status
            current_failure_count = getattr(self._status, 'failure_count', 0)
            # Calculate the open_until timestamp based on current time and cooldown
            from datetime import datetime
            open_until = (datetime.now() + self.cooldown).timestamp()
            self._status = StatusOpen(policy=self, previous_status=self._status, open_until=open_until)
        else:  # HALF_OPEN
            # When transitioning to HALF_OPEN, reset failure count
            self._status = StatusHalfOpen(policy=self, failure_count=0)

        self.on_status_change(old_status, new_status)
        self._save_state()  # Persist state change

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
                self._save_state()  # Persist state after exception
                raise
            else:
                self._status.mark_success()
                self._save_state()  # Persist state after success
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

    def __init__(self, policy: CircuitProtectorPolicy, failure_count: int = 0):
        super().__init__(policy)
        # Initialize failure_count for StatusClosed
        self.failure_count = failure_count
        self.execution_log = BinaryCircularBuffer(size=policy.failure_limit.denominator)

    def validate_execution(self) -> None:
        # In the CLOSED status, execution is allowed
        pass

    def mark_failure(self) -> None:
        self.failure_count += 1  # Increment failure count
        self.execution_log.add(False)
        if (
            self.execution_log.is_full
            and self.execution_log.failure_rate >= self.policy.failure_limit
        ):
            self.policy.status = CircuitStatus.OPEN

    def mark_success(self) -> None:
        self.failure_count = 0  # Reset failure count on success
        self.execution_log.add(True)


class StatusOpen(CircuitStatusBase):
    status_type = CircuitStatus.OPEN

    def __init__(self, policy: CircuitProtectorPolicy, previous_status: CircuitStatusBase, open_until: float = 0) -> None:
        super().__init__(policy)
        self.execution_log = previous_status.execution_log
        # Handle setting failure_count from previous_status if it exists
        if hasattr(previous_status, 'failure_count'):
            self.failure_count = getattr(previous_status, 'failure_count', 0)
        else:
            self.failure_count = 0

        # Store the timestamp when the OPEN state should end (cooldown period)
        # If open_until is 0, circuit should be blocked for the full cooldown period
        from datetime import datetime
        if open_until and open_until > 0:
            self.open_until_timestamp = open_until  # This is when cooldown ends
        else:
            # Calculate when cooldown should end based on current time and policy cooldown
            self.open_until_timestamp = (datetime.now() + policy.cooldown).timestamp()

    def validate_execution(self) -> None:
        from datetime import datetime
        # Check if cooldown period has expired
        if datetime.now().timestamp() >= self.open_until_timestamp:
            # Cooldown expired, transition to HALF_OPEN to allow test requests
            self.policy.status = CircuitStatus.HALF_OPEN
            return  # Allow execution in HALF_OPEN state

        # Still in cooldown period, block execution
        raise ProtectedCallError

    def mark_failure(self) -> None:
        # In OPEN status, errors are not recorded because execution is blocked
        pass

    def mark_success(self) -> None:
        self.policy.status = CircuitStatus.HALF_OPEN


class StatusHalfOpen(CircuitStatusBase):
    status_type = CircuitStatus.HALF_OPEN

    def __init__(self, policy: CircuitProtectorPolicy, failure_count: int = 0):
        super().__init__(policy)
        self.failure_count = failure_count
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
        self.failure_count += 1
        self.execution_log.add(False)
        self._check_limit()

    def mark_success(self) -> None:
        self.failure_count = 0  # Reset on success
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
