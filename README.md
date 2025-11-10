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

### Basic Circuit Protector

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitProtectorPolicy

# Create a circuit protector that trips after 3 failures
protector = CircuitProtectorPolicy(
    failure_limit=Fraction(3, 10),  # 3 out of 10 failures
    cooldown=timedelta(seconds=30)      # 30-second cooldown
)

@protector
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
from highway_circutbreaker import RetryWithBackoffPolicy, ExponentialDelay

# Create an exponential backoff strategy
backoff = ExponentialDelay(
    min_delay=timedelta(seconds=1),
    max_delay=timedelta(seconds=10),
    factor=2,
    jitter=0.1
)

# Apply retry policy with backoff
retry_policy = RetryWithBackoffPolicy(
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

### Combining Circuit Protector and Retry

```python
from highway_circutbreaker import SafetyNet, CircuitProtectorPolicy, RetryWithBackoffPolicy

# Combine both patterns using SafetyNet
safety_net = SafetyNet(
    policies=(
        RetryWithBackoffPolicy(max_retries=2),
        CircuitProtectorPolicy(failure_limit=Fraction(2, 5))
    )
)

@safety_net
def resilient_external_api_call():
    # This will first retry, then circuit-protect if needed
    import requests
    response = requests.get("https://external-api.example.com/data")
    return response.json()
```

## Detailed Examples

### Circuit Protector Customization

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitProtectorPolicy, CircuitState

def custom_exception_handler(exc):
    """Only handle specific exceptions"""
    return isinstance(exc, (ConnectionError, TimeoutError))

def status_change_handler(policy, old_status, new_status):
    """Handle status transitions"""
    print(f"Circuit protector changed status: {old_status.name} -> {new_status.name}")

# Fully customized circuit protector
custom_protector = CircuitProtectorPolicy(
    cooldown=timedelta(minutes=1),                      # 1-minute cooldown
    failure_limit=Fraction(3, 10),                 # Trip after 30% failure rate
    success_limit=Fraction(5, 5),                  # Close after 5 consecutive successes
    should_handle=custom_exception_handler,                   # Custom exception filter
    on_status_change=status_change_handler              # Status change listener
)

@custom_protector
def monitored_service_call():
    # Your service call with enhanced monitoring
    pass
```

### Complex Retry Scenarios

```python
from highway_circutbreaker import RetryWithBackoffPolicy, FixedDelay

# Constant delay between retries
constant_backoff = FixedDelay(delay=timedelta(seconds=2))

retry_with_constant_backoff = RetryWithBackoffPolicy(
    max_retries=5,
    backoff=constant_backoff,
    should_handle=lambda e: isinstance(e, ConnectionError)
)

@retry_with_constant_backoff
def service_with_constant_retry():
    # This will retry every 2 seconds up to 5 times
    pass
```

### Accessing Circuit Protector Status

```python
from highway_circutbreaker import CircuitProtectorPolicy

protector = CircuitProtectorPolicy(failure_limit=Fraction(2, 5))

@protector
def service_call():
    pass

# Check protector status and execution log
print(f"Current status: {protector.status.name}")
print(f"Execution log: {list(protector.execution_log)}")

# The execution_log buffer maintains success/failure record
if protector.status == CircuitState.OPEN:
    print("Circuit protector is currently open - requests are blocked")
else:
    service_call()  # Execute call if not in OPEN status
```

## Highway Workflow Engine Integration

Highway Circuit Breaker is a core component of the Highway Workflow Engine, designed for building resilient, distributed applications. The Highway Workflow Engine provides:

- **Workflow Orchestration**: Define complex business processes
- **Task Management**: Execute and monitor long-running tasks
- **Resilience Patterns**: Built-in fault tolerance with circuit breakers and retries
- **Monitoring & Observability**: Track workflow execution and identify bottlenecks

Learn more about the complete Highway Workflow Engine at [highway-workflow-engine.readthedocs.io](https://highway-workflow-engine.readthedocs.io).

## API Reference

### CircuitProtectorPolicy

Implements the circuit protector pattern with three statuses: CLOSED, OPEN, HALF_OPEN.

**Parameters:**
- `cooldown` (timedelta): Duration before transitioning from OPEN to HALF_OPEN
- `failure_limit` (Fraction): Failure rate to trip the protector (e.g., Fraction(3, 10) for 3 out of 10)
- `success_limit` (Fraction): Success rate to close the protector in HALF_OPEN status
- `should_handle` (Callable): Predicate to determine which exceptions to count as failures
- `on_status_change` (Callable): Callback when the protector changes status

### RetryWithBackoffPolicy

Implements the retry pattern with configurable backoff strategies.

**Parameters:**
- `backoff` (ExponentialDelay | FixedDelay): Backoff strategy between retries
- `max_retries` (int): Maximum number of retry attempts
- `should_handle` (Callable): Predicate to determine which exceptions to retry

### SafetyNet

Combines multiple policies for comprehensive error handling.

**Parameters:**
- `policies` (tuple): Tuple of policies to apply

### ExponentialDelay Strategies

- `ExponentialDelay`: Exponential backoff with configurable parameters
- `FixedDelay`: Constant delay between attempts

## Best Practices

1. **Configure Appropriate Limits**: Set failure limits based on your service's expected error rate
2. **Use Meaningful Cooldown Periods**: Balance between detecting recovery and avoiding thrashing
3. **Handle Specific Exceptions**: Use the `should_handle` parameter to only respond to expected failures
4. **Monitor Status Changes**: Use `on_status_change` to detect and log circuit protector transitions
5. **Chain Policies Thoughtfully**: Apply retry before circuit protector for optimal resilience

## Contributing

We welcome contributions to Highway Circuit Breaker! See our [contributing guide](CONTRIBUTING.md) for details.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

## Support

Need help? Check out our documentation or open an issue on GitHub.

---

*Part of the Highway Workflow Engine family of resilience tools*