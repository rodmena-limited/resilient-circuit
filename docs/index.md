# Resilient Circuit Documentation

Welcome to the Resilient Circuit documentation. This library is part of the Highway Workflow Engine, a comprehensive solution for building resilient and fault-tolerant applications.

## Table of Contents
1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Core Concepts](#core-concepts)
4. [Circuit Protector Pattern](#circuit-protector-pattern)
5. [Retry Pattern](#retry-pattern)
6. [SafetyNet Pattern](#safetynet-pattern)
7. [Advanced Usage](#advanced-usage)
8. [Integration with Highway Workflow Engine](#integration-with-highway-workflow-engine)

## Introduction

Resilient Circuit is a Python library that implements resilience patterns to help your applications gracefully handle failures in distributed systems. It provides implementations of the Circuit Protector and Retry patterns, which are essential for building fault-tolerant services.

### Why Use Resilient Circuit?

- **Prevents Cascading Failures**: Stop failures from spreading through your system
- **Improves User Experience**: Handle temporary outages gracefully
- **Reduces Load on Failing Services**: Avoid overwhelming already struggling services
- **Easy Integration**: Simple decorator-based API
- **Composable**: Combine multiple resilience strategies

## Installation

```bash
pip install resilient_circuit
```

## Core Concepts

### The Circuit Protector Status Machine

The Circuit Protector operates in three statuses:
- **CLOSED**: Normal operation, requests are allowed
- **OPEN**: All requests are blocked immediately
- **HALF_OPEN**: Test requests are allowed to determine if the service has recovered

### The Retry Pattern

Retries are useful for handling temporary failures by attempting an operation multiple times before giving up.

## Circuit Protector Pattern

### Basic Usage

```python
from datetime import timedelta
from fractions import Fraction
from resilient_circuit import CircuitProtectorPolicy

# Create a circuit protector
protector = CircuitProtectorPolicy(
    cooldown=timedelta(seconds=30),
    failure_limit=Fraction(2, 5)
)

@protector
def external_service_call():
    # Potentially unreliable service call
    pass
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| cooldown | timedelta | Duration before transitioning from OPEN to HALF_OPEN |
| failure_limit | Fraction | Fraction of failures to trip the circuit |
| success_limit | Fraction | Fraction of successes to close the circuit in HALF_OPEN status |
| should_handle | Callable | Predicate to determine which exceptions count as failures |
| on_status_change | Callable | Callback when the circuit protector changes status |

### Status Transitions

- **CLOSED → OPEN**: When failure rate exceeds `failure_limit`
- **OPEN → HALF_OPEN**: After cooldown period expires
- **HALF_OPEN → CLOSED**: When success rate meets `success_limit`
- **HALF_OPEN → OPEN**: When failure rate meets limit

## Retry Pattern

### Basic Usage

```python
from resilient_circuit import RetryWithBackoffPolicy

retry_policy = RetryWithBackoffPolicy(max_retries=3)

@retry_policy
def flaky_operation():
    # Operation that might fail temporarily
    pass
```

### With Backoff Strategy

```python
from datetime import timedelta
from resilient_circuit import RetryWithBackoffPolicy, ExponentialDelay

backoff = ExponentialDelay(
    min_delay=timedelta(seconds=1),
    max_delay=timedelta(seconds=10),
    factor=2,
    jitter=0.1
)

retry_with_backoff = RetryWithBackoffPolicy(
    max_retries=3,
    backoff=backoff
)

@retry_with_backoff
def operation_with_backoff():
    # Will retry with increasing delays
    pass
```

## SafetyNet Pattern

The SafetyNet pattern combines multiple policies:

```python
from resilient_circuit import SafetyNet, RetryWithBackoffPolicy, CircuitProtectorPolicy

safety_net = SafetyNet(
    policies=(
        RetryWithBackoffPolicy(max_retries=2),
        CircuitProtectorPolicy(failure_limit=Fraction(2, 5))
    )
)

@safety_net
def resilient_operation():
    # First retries, then circuit protector if needed
    pass
```

## Advanced Usage

### Custom Exception Handling

```python
def is_retryable_exception(exc):
    return isinstance(exc, (ConnectionError, TimeoutError))

retry_policy = RetryWithBackoffPolicy(
    max_retries=3,
    should_handle=is_retryable_exception
)
```

### Monitoring Status Changes

```python
def handle_status_change(policy, old_status, new_status):
    print(f"Circuit protector status changed: {old_status} -> {new_status}")

protector = CircuitProtectorPolicy(
    cooldown=timedelta(seconds=30),
    on_status_change=handle_status_change
)
```

### Accessing Execution Log

```python
protector = CircuitProtectorPolicy(failure_limit=Fraction(2, 5))

@protector
def service_call():
    # Your operation
    pass

# Access historical data
print(f"Current status: {protector.status}")
print(f"Recent successes/failures: {list(protector.execution_log)}")
```

## Integration with Highway Workflow Engine

Resilient Circuit is designed as a core component of the Highway Workflow Engine, providing resilience capabilities for workflow orchestration. The Highway Workflow Engine is a distributed workflow management system that leverages Resilient Circuit to:

- Automatically handle failures in workflow steps
- Provide graceful degradation when external services are unavailable
- Maintain system reliability under partial failure conditions
- Enable rapid recovery through circuit protector's status management

When used together, the Highway Workflow Engine and Resilient Circuit provide a comprehensive solution for building robust, distributed applications that can withstand network failures, service outages, and other common distributed system challenges.

## Best Practices

1. **Set Appropriate Limits**: Configure failure limits based on your service's typical error rates
2. **Use Meaningful Cooldowns**: Balance between detecting recovery and avoiding thrashing
3. **Monitor in Production**: Track circuit protector statuses and failure rates
4. **Test Your Configuration**: Verify your resilience patterns under various failure scenarios
5. **Combine Patterns Thoughtfully**: Use safety net to combine policies in the right order

## Troubleshooting

### Circuit Protector Stays Open

If your circuit protector stays in the OPEN status longer than expected:
- Check that your cooldown period is appropriate
- Verify that your success limit can be met
- Ensure your service has actually recovered

### Retries Exceeding Expected Count

If operations are being retried more than configured:
- Verify your `should_handle` predicate correctly identifies retryable exceptions
- Check for exceptions being raised within your retry policy