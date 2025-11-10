# Highway Circuit Breaker Documentation

Welcome to the Highway Circuit Breaker documentation. This library is part of the Highway Workflow Engine, a comprehensive solution for building resilient and fault-tolerant applications.

## Table of Contents
1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Core Concepts](#core-concepts)
4. [Circuit Breaker Pattern](#circuit-breaker-pattern)
5. [Retry Pattern](#retry-pattern)
6. [Failsafe Pattern](#failsafe-pattern)
7. [Advanced Usage](#advanced-usage)
8. [Integration with Highway Workflow Engine](#integration-with-highway-workflow-engine)

## Introduction

Highway Circuit Breaker is a Python library that implements resilience patterns to help your applications gracefully handle failures in distributed systems. It provides implementations of the Circuit Breaker and Retry patterns, which are essential for building fault-tolerant services.

### Why Use Highway Circuit Breaker?

- **Prevents Cascading Failures**: Stop failures from spreading through your system
- **Improves User Experience**: Handle temporary outages gracefully
- **Reduces Load on Failing Services**: Avoid overwhelming already struggling services
- **Easy Integration**: Simple decorator-based API
- **Composable**: Combine multiple resilience strategies

## Installation

```bash
pip install highway_circutbreaker
```

## Core Concepts

### The Circuit Breaker State Machine

The Circuit Breaker operates in three states:
- **CLOSED**: Normal operation, requests are allowed
- **OPEN**: All requests are blocked immediately
- **HALF_OPEN**: Test requests are allowed to determine if the service has recovered

### The Retry Pattern

Retries are useful for handling temporary failures by attempting an operation multiple times before giving up.

## Circuit Breaker Pattern

### Basic Usage

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy

# Create a circuit breaker
breaker = CircuitBreakerPolicy(
    cooldown=timedelta(seconds=30),
    failure_threshold=Fraction(2, 5)
)

@breaker
def external_service_call():
    # Potentially unreliable service call
    pass
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| cooldown | timedelta | Duration before transitioning from OPEN to HALF_OPEN |
| failure_threshold | Fraction | Fraction of failures to trip the circuit |
| success_threshold | Fraction | Fraction of successes to close the circuit in HALF_OPEN state |
| handle | Callable | Predicate to determine which exceptions count as failures |
| on_state_change | Callable | Callback when the circuit breaker changes state |

### State Transitions

- **CLOSED → OPEN**: When failure rate exceeds `failure_threshold`
- **OPEN → HALF_OPEN**: After cooldown period expires
- **HALF_OPEN → CLOSED**: When success rate meets `success_threshold`
- **HALF_OPEN → OPEN**: When failure rate meets threshold

## Retry Pattern

### Basic Usage

```python
from highway_circutbreaker import RetryPolicy

retry_policy = RetryPolicy(max_retries=3)

@retry_policy
def flaky_operation():
    # Operation that might fail temporarily
    pass
```

### With Backoff Strategy

```python
from datetime import timedelta
from highway_circutbreaker import RetryPolicy, Backoff

backoff = Backoff(
    min_delay=timedelta(seconds=1),
    max_delay=timedelta(seconds=10),
    factor=2,
    jitter=0.1
)

retry_with_backoff = RetryPolicy(
    max_retries=3,
    backoff=backoff
)

@retry_with_backoff
def operation_with_backoff():
    # Will retry with increasing delays
    pass
```

## Failsafe Pattern

The Failsafe pattern combines multiple policies:

```python
from highway_circutbreaker import Failsafe, RetryPolicy, CircuitBreakerPolicy

failsafe = Failsafe(
    policies=(
        RetryPolicy(max_retries=2),
        CircuitBreakerPolicy(failure_threshold=Fraction(2, 5))
    )
)

@failsafe
def resilient_operation():
    # First retries, then circuit breaker if needed
    pass
```

## Advanced Usage

### Custom Exception Handling

```python
def is_retryable_exception(exc):
    return isinstance(exc, (ConnectionError, TimeoutError))

retry_policy = RetryPolicy(
    max_retries=3,
    handle=is_retryable_exception
)
```

### Monitoring State Changes

```python
def handle_state_change(policy, old_state, new_state):
    print(f"Circuit breaker state changed: {old_state} -> {new_state}")

breaker = CircuitBreakerPolicy(
    cooldown=timedelta(seconds=30),
    on_state_change=handle_state_change
)
```

### Accessing Execution History

```python
breaker = CircuitBreakerPolicy(failure_threshold=Fraction(2, 5))

@breaker
def service_call():
    # Your operation
    pass

# Access historical data
print(f"Current state: {breaker.state}")
print(f"Recent successes/failures: {list(breaker.history)}")
```

## Integration with Highway Workflow Engine

Highway Circuit Breaker is designed as a core component of the Highway Workflow Engine, providing resilience capabilities for workflow orchestration. The Highway Workflow Engine is a distributed workflow management system that leverages Highway Circuit Breaker to:

- Automatically handle failures in workflow steps
- Provide graceful degradation when external services are unavailable
- Maintain system reliability under partial failure conditions
- Enable rapid recovery through circuit breaker's state management

When used together, the Highway Workflow Engine and Highway Circuit Breaker provide a comprehensive solution for building robust, distributed applications that can withstand network failures, service outages, and other common distributed system challenges.

## Best Practices

1. **Set Appropriate Thresholds**: Configure failure thresholds based on your service's typical error rates
2. **Use Meaningful Cooldowns**: Balance between detecting recovery and avoiding thrashing
3. **Monitor in Production**: Track circuit breaker states and failure rates
4. **Test Your Configuration**: Verify your resilience patterns under various failure scenarios
5. **Combine Patterns Thoughtfully**: Use failsafe to combine policies in the right order

## Troubleshooting

### Circuit Breaker Stays Open

If your circuit breaker stays in the OPEN state longer than expected:
- Check that your cooldown period is appropriate
- Verify that your success threshold can be met
- Ensure your service has actually recovered

### Retries Exceeding Expected Count

If operations are being retried more than configured:
- Verify your `handle` predicate correctly identifies retryable exceptions
- Check for exceptions being raised within your retry policy