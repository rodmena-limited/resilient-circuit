# Highway Circuit Breaker

<div align="center">

[![PyPI version](https://badge.fury.io/py/highway-circutbreaker.svg)](https://badge.fury.io/py/highway-circutbreaker)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Versions](https://img.shields.io/pypi/pyversions/highway-circutbreaker.svg)](https://pypi.org/project/highway-circutbreaker/)

**Part of the Highway Workflow Engine** - A robust resilience library for Python applications
</div>

---

## Overview

Highway Circuit Breaker is a powerful resilience library designed to make your Python applications fault-tolerant and highly available. It's an integral component of the Highway Workflow Engine, providing essential failure handling capabilities for modern distributed systems.

This library implements the Circuit Breaker and Retry patterns, offering elegant solutions for handling failures in networked systems, external service calls, and unreliable dependencies.

## Installation

```bash
pip install highway_circutbreaker
```

## Features

- **Circuit Breaker Pattern**: Prevents cascading failures in distributed systems
- **Retry Pattern**: Automatically retries failed operations with configurable backoff
- **Composable**: Chain multiple policies together for sophisticated error handling
- **Decorator Support**: Clean, easy-to-read syntax with Python decorators
- **Fine-grained Control**: Configure failure thresholds, cooldown periods, and backoff strategies
- **State Monitoring**: Track breaker state and execution history

## Quick Start

### Basic Circuit Breaker

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy

# Create a circuit breaker that trips after 3 failures
breaker = CircuitBreakerPolicy(
    failure_threshold=Fraction(3, 10),  # 3 out of 10 failures
    cooldown=timedelta(seconds=30)      # 30-second cooldown
)

@breaker
def unreliable_service_call():
    # Your potentially failing external service call
    import random
    if random.random() < 0.7:
        raise Exception("Service temporarily unavailable")
    return "Success!"
```

### Advanced Retry with Exponential Backoff

```python
from datetime import timedelta
from highway_circutbreaker import RetryPolicy, Backoff

# Create an exponential backoff strategy
backoff = Backoff(
    min_delay=timedelta(seconds=1),
    max_delay=timedelta(seconds=10),
    factor=2,
    jitter=0.1
)

# Apply retry policy with backoff
retry_policy = RetryPolicy(
    max_retries=3,
    backoff=backoff
)

@retry_policy
def unreliable_database_operation():
    # Operation that might fail temporarily
    import random
    if random.random() < 0.5:
        raise ConnectionError("Database temporarily unavailable")
    return "Database operation completed"
```

### Combining Circuit Breaker and Retry

```python
from highway_circutbreaker import Failsafe, CircuitBreakerPolicy, RetryPolicy

# Combine both patterns using Failsafe
failsafe = Failsafe(
    policies=(
        RetryPolicy(max_retries=2),
        CircuitBreakerPolicy(failure_threshold=Fraction(2, 5))
    )
)

@failsafe
def resilient_external_api_call():
    # This will first retry, then circuit-break if needed
    import requests
    response = requests.get("https://external-api.example.com/data")
    return response.json()
```

## Detailed Examples

### Circuit Breaker Customization

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy, CircuitBreakerState

def custom_exception_handler(exc):
    """Only handle specific exceptions"""
    return isinstance(exc, (ConnectionError, TimeoutError))

def state_change_handler(policy, old_state, new_state):
    """Handle state transitions"""
    print(f"Circuit breaker changed state: {old_state.name} -> {new_state.name}")

# Fully customized circuit breaker
custom_breaker = CircuitBreakerPolicy(
    cooldown=timedelta(minutes=1),                      # 1-minute cooldown
    failure_threshold=Fraction(3, 10),                 # Trip after 30% failure rate
    success_threshold=Fraction(5, 5),                  # Close after 5 consecutive successes
    handle=custom_exception_handler,                   # Custom exception filter
    on_state_change=state_change_handler              # State change listener
)

@custom_breaker
def monitored_service_call():
    # Your service call with enhanced monitoring
    pass
```

### Complex Retry Scenarios

```python
from highway_circutbreaker import RetryPolicy, Delay

# Constant delay between retries
constant_backoff = Delay(delay=timedelta(seconds=2))

retry_with_constant_backoff = RetryPolicy(
    max_retries=5,
    backoff=constant_backoff,
    handle=lambda e: isinstance(e, ConnectionError)
)

@retry_with_constant_backoff
def service_with_constant_retry():
    # This will retry every 2 seconds up to 5 times
    pass
```

### Accessing Circuit Breaker State

```python
from highway_circutbreaker import CircuitBreakerPolicy

breaker = CircuitBreakerPolicy(failure_threshold=Fraction(2, 5))

@breaker
def service_call():
    pass

# Check breaker state and history
print(f"Current state: {breaker.state.name}")
print(f"Execution history: {list(breaker.history)}")

# The history buffer maintains success/failure record
if breaker.state == CircuitBreakerState.OPEN:
    print("Circuit breaker is currently open - requests are blocked")
else:
    service_call()  # Execute call if not in OPEN state
```

## Highway Workflow Engine Integration

Highway Circuit Breaker is a core component of the Highway Workflow Engine, designed for building resilient, distributed applications. The Highway Workflow Engine provides:

- **Workflow Orchestration**: Define complex business processes
- **Task Management**: Execute and monitor long-running tasks
- **Resilience Patterns**: Built-in fault tolerance with circuit breakers and retries
- **Monitoring & Observability**: Track workflow execution and identify bottlenecks

Learn more about the complete Highway Workflow Engine at [highway-workflow-engine.readthedocs.io](https://highway-workflow-engine.readthedocs.io).

## API Reference

### CircuitBreakerPolicy

Implements the circuit breaker pattern with three states: CLOSED, OPEN, HALF_OPEN.

**Parameters:**
- `cooldown` (timedelta): Duration before transitioning from OPEN to HALF_OPEN
- `failure_threshold` (Fraction): Failure rate to trip the breaker (e.g., Fraction(3, 10) for 3 out of 10)
- `success_threshold` (Fraction): Success rate to close the breaker in HALF_OPEN state
- `handle` (Callable): Predicate to determine which exceptions to count as failures
- `on_state_change` (Callable): Callback when the breaker changes state

### RetryPolicy

Implements the retry pattern with configurable backoff strategies.

**Parameters:**
- `backoff` (Backoff | Delay): Backoff strategy between retries
- `max_retries` (int): Maximum number of retry attempts
- `handle` (Callable): Predicate to determine which exceptions to retry

### Failsafe

Combines multiple policies for comprehensive error handling.

**Parameters:**
- `policies` (tuple): Tuple of policies to apply

### Backoff Strategies

- `Backoff`: Exponential backoff with configurable parameters
- `Delay`: Constant delay between attempts

## Best Practices

1. **Configure Appropriate Thresholds**: Set failure thresholds based on your service's expected error rate
2. **Use Meaningful Cooldown Periods**: Balance between detecting recovery and avoiding thrashing
3. **Handle Specific Exceptions**: Use the `handle` parameter to only respond to expected failures
4. **Monitor State Changes**: Use `on_state_change` to detect and log circuit breaker transitions
5. **Chain Policies Thoughtfully**: Apply retry before circuit breaker for optimal resilience

## Contributing

We welcome contributions to Highway Circuit Breaker! See our [contributing guide](CONTRIBUTING.md) for details.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

## Support

Need help? Check out our documentation or open an issue on GitHub.

---

*Part of the Highway Workflow Engine family of resilience tools*