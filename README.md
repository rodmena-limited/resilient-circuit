# highway_circutbreaker
Library for handling failures.

## Installation
```bash
pip install highway_circutbreaker
```

## Usage

### Policies
Currently, we support two policies: `Retry` and `CircuitBreaker`.
Detailed documentation can be found below.

### Retry
##### class RetryPolicy
Retry policy allows you to configure how result of execution of a given callable must be retried.

_Parameters:_

- backoff: `Optional[Backoff] = None` - backoff configuration;
- max_retries: `int = 3` - maximum number of times supplied function will be called;
- handle: `Callable[[Exception], bool]` - predicate defining whether an exception can be handled (deemed as failure to be retried). By default, all exceptions are handled.


_Raises:_

- `RetriesExceeded` - when callable cannot be retried due to exceeding number of attempts. Preserves original exception context.

Can be used as a decorator:
```python
from highway_circutbreaker import RetryPolicy

@RetryPolicy(max_retries=2)
def my_function() -> None:
    print("my function")
``` 

##### class Backoff
Defines configuration of backoff to compute delays between calls.

Formula: `delay = min_delay * pow(factor, attempt-1)`

_Parameters:_

- min_delay: `timedelta` - initial (thus minimal) delay;
- max_delay: `timedelta` - computed delay will not exceed this value;
- factor: `int = 2` - factor;
- jitter: `Optional[float]` - jitter coefficient. Must be in range `[0, 1]`. A random portion of `delay * jitter` will be added to or subtracted from the total `delay`.

_Methods:_

- `for_attempt(attempt: int) -> float` - compute delay in seconds for a given attempt. 

##### class Delay
Subclass of `Backoff` that defines constant delay between subsequent calls.

_Parameters:_

- delay: `timedelta` - delay between calls

### Circuit Breaker
For more details on ideas behind Circuit Breaker please read 
[this article](https://martinfowler.com/bliki/CircuitBreaker.html).

#### Class CircuitBreakerPolicy
Circuit Breaker allows you to configure how execution of a given callable must be interrupted.

_Parameters:_

- cooldown: `timedelta = 0` - duration after which breaker transitions `OPEN -> HALF_OPEN`
- failure_threshold: `Fraction = 1 of 1` - amount of failures over total number of executions before breaker trips `CLOSED -> OPEN`
- success_threshold: `Fraction = 1 of 1` - amount of successes over total number of executions before breaker closes `HALF_OPEN -> CLOSED`. If not set `failure_threshold` is used instead.
- handle: `Callable[[Exception], bool]` - predicate defining whether an exception can be handled (deemed as failure to be counted towards failures). By default, all exceptions are handled.
- on_state_change: `Callable[[CircuitBreakerPolicy, State, State], None]` - method which will be called every time state of CircuitBreaker is changed.


_Raises:_

- `CircuitBreakerOpenError` - when CircuitBreaker is in `OPEN` state.

Can be used as a decorator:
```python
from datetime import timedelta
from highway_circutbreaker import CircuitBreakerPolicy

@CircuitBreakerPolicy(cooldown=timedelta(seconds=2))
def my_function() -> None:
    print("my function")
``` 

_Methods and Properties:_

- `(method) on_state_changed(self, current: CircuitBreakerState, new: CircuitBreakerState) -> None` - called whenever CircuitBreaker changes its state
- `(property) history -> CircularBuffer` - history of recent calls capped at threshold's denominator. When state is `OPEN` provides history of the previous state
- `(property) state -> CircuitBreakerState` - current state of the CircuitBreaker

#### Enum CircuitBreakerState
- CLOSED
- OPEN
- HALF_OPEN

### Failsafe
Provided interface to apply multiple policies at once. 
It will handle execution results in reverse, with last policy applied first.

Example:
```python
from highway_circutbreaker import Failsafe, RetryPolicy, CircuitBreakerPolicy

@Failsafe(policies=(RetryPolicy(), CircuitBreakerPolicy()))
def my_function() -> None:
    print("my function")

# Equivalent to:

@RetryPolicy()
@CircuitBreakerPolicy()
def my_function() -> None:
    print("my function")
```


## Library development
1. install dependencies
```bash
poetry install
```
2. run all checks
```bash
poetry run make verify
```
3. enter virtualenv managed by poetry
```bash
poetry shell
```

---
_Maintained by the Python Platform team - Slack_ ___#p-python-platform___
