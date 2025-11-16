# Resilient Circuit - API Reference

This document provides a comprehensive reference for the Resilient Circuit API.

## Classes

### CircuitProtectorPolicy

Implements the circuit breaker pattern to prevent cascading failures in distributed systems.

```python
from datetime import timedelta
from fractions import Fraction
from resilient_circuit import CircuitProtectorPolicy

CircuitProtectorPolicy(
    cooldown: timedelta = timedelta(0),
    failure_limit: Fraction = Fraction(1, 1),
    success_limit: Fraction = Fraction(1, 1),
    should_handle: Callable[[Exception], bool] = lambda e: True,
    on_status_change: Optional[Callable[["CircuitProtectorPolicy", CircuitStatus, CircuitStatus], None]] = None
)
```

#### Parameters

- **cooldown** (`timedelta`): Duration to wait before transitioning from `OPEN` to `HALF_OPEN` status
- **failure_limit** (`Fraction`): Fraction of failures over total executions that will trip the circuit protector from `CLOSED` to `OPEN`
- **success_limit** (`Fraction`): Fraction of successes that will close the circuit protector from `HALF_OPEN` to `CLOSED`. If not set, `failure_limit` is used instead
- **should_handle** (`Callable[[Exception], bool]`): Predicate to determine which exceptions count as failures. By default, all exceptions are handled
- **on_status_change** (`Callable[[CircuitProtectorPolicy, CircuitStatus, CircuitStatus], None]`): Function called when the circuit protector changes status

#### Properties

- **status** (`CircuitState`): Current status of the circuit protector (`CLOSED`, `OPEN`, or `HALF_OPEN`)
- **execution_log** (`BinaryCircularBuffer`): Log of recent successes and failures

#### Methods

- **on_status_change**(current: `CircuitState`, new: `CircuitState`) → None: Called when the circuit protector changes status

### RetryWithBackoffPolicy

Implements the retry pattern to automatically retry failed operations.

```python
from datetime import timedelta
from resilient_circuit import RetryWithBackoffPolicy, ExponentialDelay

RetryWithBackoffPolicy(
    backoff: Optional[ExponentialDelay] = None,
    max_retries: int = 3,
    should_handle: Callable[[Exception], bool] = lambda e: True
)
```

#### Parameters

- **backoff** (`ExponentialDelay`): Backoff strategy to use between retries. If None, retries happen immediately
- **max_retries** (`int`): Maximum number of retry attempts (default: 3)
- **should_handle** (`Callable[[Exception], bool]`): Predicate to determine which exceptions should be retried. By default, all exceptions are retried

### SafetyNet

Combines multiple policies to provide comprehensive error handling.

```python
from resilient_circuit import SafetyNet

SafetyNet(policies: tuple)
```

#### Parameters

- **policies** (`tuple`): Tuple of policy instances to apply

### ExponentialDelay

Base class for implementing backoff strategies between retries.

```python
from datetime import timedelta
from resilient_circuit import ExponentialDelay

ExponentialDelay(
    min_delay: timedelta,
    max_delay: timedelta,
    factor: int = 2,
    jitter: Optional[float] = None
)
```

#### Parameters

- **min_delay** (`timedelta`): Initial (minimum) delay
- **max_delay** (`timedelta`): Maximum delay that will not be exceeded
- **factor** (`int`): Multiplier for delay progression (default: 2)
- **jitter** (`float`): Jitter coefficient, must be between 0 and 1 (optional)

#### Formula

The backoff delay is calculated as: `min_delay * pow(factor, attempt-1)`

#### Methods

- **for_attempt**(attempt: `int`) → `float`: Calculate delay in seconds for a given attempt number

### FixedDelay

A subclass of `ExponentialDelay` that implements constant delay between retries.

```python
from datetime import timedelta
from resilient_circuit import FixedDelay

FixedDelay(delay: timedelta)
```

#### Parameters

- **delay** (`timedelta`): Constant delay between subsequent calls

## Enums

### CircuitState

Represents the status of a circuit protector:

- `CircuitState.CLOSED`: Normal operation, requests are allowed
- `CircuitState.OPEN`: Requests are blocked, circuit is broken
- `CircuitState.HALF_OPEN`: Testing status, limited requests allowed to determine if service has recovered

## Exceptions

### ProtectedCallError

Raised when the circuit protector is in the `OPEN` status and a request is attempted.

### RetryLimitReached

Raised when the maximum number of retries is exceeded in a `RetryWithBackoffPolicy`. Preserves the original exception context.

## Examples

### Using Circuit Protector with Custom Parameters

```python
from datetime import timedelta
from fractions import Fraction
from resilient_circuit import CircuitProtectorPolicy, CircuitState

def on_status_change(policy, old_status, new_status):
    print(f"Status changed from {old_status.name} to {new_status.name}")

protector = CircuitProtectorPolicy(
    cooldown=timedelta(seconds=60),
    failure_limit=Fraction(3, 10),
    success_limit=Fraction(5, 5),
    on_status_change=on_status_change
)

@protector
def service_call():
    # Your service call
    pass
```

### Using Retry Policy with Exponential Backoff

```python
from datetime import timedelta
from resilient_circuit import RetryWithBackoffPolicy, ExponentialDelay

exponential_backoff = ExponentialDelay(
    min_delay=timedelta(milliseconds=100),
    max_delay=timedelta(seconds=5),
    factor=2,
    jitter=0.1
)

retry_policy = RetryWithBackoffPolicy(
    max_retries=5,
    backoff=exponential_backoff
)

@retry_policy
def unreliable_operation():
    # Operation that might fail temporarily
    pass
```

### SafetyNet with Multiple Policies

```python
from resilient_circuit import SafetyNet, RetryWithBackoffPolicy, CircuitProtectorPolicy

safety_net = SafetyNet(
    policies=(
        RetryWithBackoffPolicy(max_retries=2),
        CircuitProtectorPolicy(failure_limit=Fraction(3, 10))
    )
)

@safety_net
def resilient_operation():
    # This will first apply circuit protector logic,
    # then retry logic if the protector allows the call
    pass
```