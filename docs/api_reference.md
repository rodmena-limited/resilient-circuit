# Highway Circuit Breaker - API Reference

This document provides a comprehensive reference for the Highway Circuit Breaker API.

## Classes

### CircuitBreakerPolicy

Implements the circuit breaker pattern to prevent cascading failures in distributed systems.

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy

CircuitBreakerPolicy(
    cooldown: timedelta = timedelta(0),
    failure_threshold: Fraction = Fraction(1, 1),
    success_threshold: Fraction = Fraction(1, 1),
    handle: Callable[[Exception], bool] = lambda e: True,
    on_state_change: Optional[Callable[["CircuitBreakerPolicy", State, State], None]] = None
)
```

#### Parameters

- **cooldown** (`timedelta`): Duration to wait before transitioning from `OPEN` to `HALF_OPEN` state
- **failure_threshold** (`Fraction`): Fraction of failures over total executions that will trip the circuit breaker from `CLOSED` to `OPEN`
- **success_threshold** (`Fraction`): Fraction of successes that will close the circuit breaker from `HALF_OPEN` to `CLOSED`. If not set, `failure_threshold` is used instead
- **handle** (`Callable[[Exception], bool]`): Predicate to determine which exceptions count as failures. By default, all exceptions are handled
- **on_state_change** (`Callable[[CircuitBreakerPolicy, State, State], None]`): Function called when the circuit breaker changes state

#### Properties

- **state** (`CircuitBreakerState`): Current state of the circuit breaker (`CLOSED`, `OPEN`, or `HALF_OPEN`)
- **history** (`BoolCircularBuffer`): History of recent successes and failures

#### Methods

- **on_state_change**(current: `CircuitBreakerState`, new: `CircuitBreakerState`) → None: Called when the circuit breaker changes state

### RetryPolicy

Implements the retry pattern to automatically retry failed operations.

```python
from datetime import timedelta
from highway_circutbreaker import RetryPolicy, Backoff

RetryPolicy(
    backoff: Optional[Backoff] = None,
    max_retries: int = 3,
    handle: Callable[[Exception], bool] = lambda e: True
)
```

#### Parameters

- **backoff** (`Backoff`): Backoff strategy to use between retries. If None, retries happen immediately
- **max_retries** (`int`): Maximum number of retry attempts (default: 3)
- **handle** (`Callable[[Exception], bool]`): Predicate to determine which exceptions should be retried. By default, all exceptions are retried

### Failsafe

Combines multiple policies to provide comprehensive error handling.

```python
from highway_circutbreaker import Failsafe

Failsafe(policies: tuple)
```

#### Parameters

- **policies** (`tuple`): Tuple of policy instances to apply

### Backoff

Base class for implementing backoff strategies between retries.

```python
from datetime import timedelta
from highway_circutbreaker import Backoff

Backoff(
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

### Delay

A subclass of `Backoff` that implements constant delay between retries.

```python
from datetime import timedelta
from highway_circutbreaker import Delay

Delay(delay: timedelta)
```

#### Parameters

- **delay** (`timedelta`): Constant delay between subsequent calls

## Enums

### CircuitBreakerState

Represents the state of a circuit breaker:

- `CircuitBreakerState.CLOSED`: Normal operation, requests are allowed
- `CircuitBreakerState.OPEN`: Requests are blocked, circuit is broken
- `CircuitBreakerState.HALF_OPEN`: Testing state, limited requests allowed to determine if service has recovered

## Exceptions

### CircuitBreakerOpenError

Raised when the circuit breaker is in the `OPEN` state and a request is attempted.

### RetriesExceeded

Raised when the maximum number of retries is exceeded in a `RetryPolicy`. Preserves the original exception context.

## Examples

### Using Circuit Breaker with Custom Parameters

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy, CircuitBreakerState

def on_state_change(policy, old_state, new_state):
    print(f"State changed from {old_state.name} to {new_state.name}")

breaker = CircuitBreakerPolicy(
    cooldown=timedelta(seconds=60),
    failure_threshold=Fraction(3, 10),
    success_threshold=Fraction(5, 5),
    on_state_change=on_state_change
)

@breaker
def service_call():
    # Your service call
    pass
```

### Using Retry Policy with Exponential Backoff

```python
from datetime import timedelta
from highway_circutbreaker import RetryPolicy, Backoff

exponential_backoff = Backoff(
    min_delay=timedelta(milliseconds=100),
    max_delay=timedelta(seconds=5),
    factor=2,
    jitter=0.1
)

retry_policy = RetryPolicy(
    max_retries=5,
    backoff=exponential_backoff
)

@retry_policy
def unreliable_operation():
    # Operation that might fail temporarily
    pass
```

### Failsafe with Multiple Policies

```python
from highway_circutbreaker import Failsafe, RetryPolicy, CircuitBreakerPolicy

failsafe = Failsafe(
    policies=(
        RetryPolicy(max_retries=2),
        CircuitBreakerPolicy(failure_threshold=Fraction(3, 10))
    )
)

@failsafe
def resilient_operation():
    # This will first apply circuit breaker logic,
    # then retry logic if the breaker allows the call
    pass
```