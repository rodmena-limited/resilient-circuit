# Resilient Circuit

<div align="center">

[![PyPI version](https://badge.fury.io/py/resilient-circuit.svg)](https://badge.fury.io/py/resilient-circuit)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Versions](https://img.shields.io/pypi/pyversions/resilient-circuit.svg)](https://pypi.org/project/resilient-circuit/)
[![Documentation Status](https://readthedocs.org/projects/resilient-circuit/badge/?version=latest)](https://resilient-circuit.readthedocs.io/)

**Part of the Highway Workflow Engine** - A robust resilience library for Python applications
</div>

---

## Overview

Resilient Circuit is a powerful resilience library designed to make your Python applications fault-tolerant and highly available. It's an integral component of the Highway Workflow Engine, providing essential failure handling capabilities for modern distributed systems.

This library implements the Circuit Breaker and Retry patterns, offering elegant solutions for handling failures in networked systems, external service calls, and unreliable dependencies.

For comprehensive documentation, visit our [Read the Docs page](https://resilient-circuit.readthedocs.io/).

## Installation

```bash
pip install resilient_circuit
```

### PostgreSQL Storage Support (Optional)

For shared state across multiple instances, you can use PostgreSQL as the storage backend:

```bash
pip install resilient_circuit[postgres]
```

Or install the dependencies separately:

```bash
pip install psycopg[binary] python-dotenv
```

## Features

- **Circuit Breaker Pattern**: Prevents cascading failures in distributed systems
- **Retry Pattern**: Automatically retries failed operations with configurable backoff
- **Composable**: Chain multiple policies together for sophisticated error handling
- **Decorator Support**: Clean, easy-to-read syntax with Python decorators
- **Fine-grained Control**: Configure failure thresholds, cooldown periods, and backoff strategies
- **State Monitoring**: Track breaker state and execution history
- **Shared State Storage**: Optional PostgreSQL backend for distributed applications

## Quick Start

### Basic Circuit Protector

```python
from datetime import timedelta
from fractions import Fraction
from resilient_circuit import CircuitProtectorPolicy

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
from resilient_circuit import RetryWithBackoffPolicy, ExponentialDelay

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
from resilient_circuit import SafetyNet, CircuitProtectorPolicy, RetryWithBackoffPolicy

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
from resilient_circuit import CircuitProtectorPolicy, CircuitState

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
from resilient_circuit import RetryWithBackoffPolicy, FixedDelay

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
from resilient_circuit import CircuitProtectorPolicy

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

## PostgreSQL Shared Storage

For distributed applications running across multiple instances, Resilient Circuit supports PostgreSQL as a shared storage backend. This allows circuit breaker state to be synchronized across all instances of your application.

### Setting Up PostgreSQL Storage

1. **Install PostgreSQL dependencies:**

```bash
pip install resilient_circuit[postgres]
```

2. **Create the database:**

You need to create the database first (the CLI assumes the database exists). Create it using your preferred method:

```bash
createdb -h localhost -p 5432 -U postgres resilient_circuit_db
```

Or using psql:
```sql
CREATE DATABASE resilient_circuit_db;
```

3. **Configure environment variables:**

Create a `.env` file in your project root:

```env
RC_DB_HOST=localhost
RC_DB_PORT=5432
RC_DB_NAME=resilient_circuit_db
RC_DB_USER=postgres
RC_DB_PASSWORD=your_password
```

4. **Use the CLI to set up the table:**

```bash
resilient-circuit-cli pg-setup
```

This command will read the database configuration from your environment variables and create the necessary table and indexes.

You can also use additional options:
- `--yes` to skip the confirmation prompt
- `--dry-run` to see what would be done without making changes

Example:
```bash
resilient-circuit-cli pg-setup --yes  # Skip confirmation
resilient-circuit-cli pg-setup --dry-run  # Show what would be done
```

### Using PostgreSQL Storage

Once configured, the circuit breaker will automatically use PostgreSQL storage when environment variables are present:

```python
from datetime import timedelta
from fractions import Fraction
from resilient_circuit import CircuitProtectorPolicy

# This will automatically use PostgreSQL if RC_DB_* env vars are set
circuit_breaker = CircuitProtectorPolicy(
    resource_key="payment_service",
    cooldown=timedelta(seconds=60),
    failure_limit=Fraction(5, 10),  # 50% failure rate
    success_limit=Fraction(3, 3)    # 3 consecutive successes to close
)

@circuit_breaker
def process_payment():
    # Your payment processing logic
    pass
```

### Benefits of PostgreSQL Storage

- **Shared State**: Circuit breaker state is synchronized across all application instances
- **Persistence**: State survives application restarts
- **Monitoring**: Query circuit breaker state directly from the database
- **Scalability**: Supports high-concurrency applications
- **Atomic Operations**: Uses PostgreSQL row-level locking for thread-safe updates

### Monitoring Circuit Breakers

Query the database to monitor circuit breaker status:

```sql
-- View all circuit breakers and their status
SELECT resource_key, state, failure_count, open_until, updated_at
FROM rc_circuit_breakers
ORDER BY updated_at DESC;

-- Find all open circuit breakers
SELECT resource_key, open_until
FROM rc_circuit_breakers
WHERE state = 'OPEN';

-- Check failure rates for specific services
SELECT resource_key, failure_count
FROM rc_circuit_breakers
WHERE state = 'CLOSED';
```

### Fallback to In-Memory Storage

If PostgreSQL is not configured or unavailable, the circuit breaker automatically falls back to in-memory storage:

```python
# No environment variables set - uses in-memory storage
circuit_breaker = CircuitProtectorPolicy(resource_key="my_service")

# Or explicitly specify in-memory storage
from resilient_circuit.storage import InMemoryStorage

circuit_breaker = CircuitProtectorPolicy(
    resource_key="my_service",
    storage=InMemoryStorage()
)
```

### Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `RC_DB_HOST` | PostgreSQL host | Required |
| `RC_DB_PORT` | PostgreSQL port | `5432` |
| `RC_DB_NAME` | Database name | `resilient_circuit_db` |
| `RC_DB_USER` | Database user | `postgres` |
| `RC_DB_PASSWORD` | Database password | Required |

## Highway Workflow Engine Integration

Resilient Circuit is a core component of the Highway Workflow Engine, designed for building resilient, distributed applications. The Highway Workflow Engine provides:

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

We welcome contributions to Resilient Circuit! See our [contributing guide](CONTRIBUTING.md) for details.

## License

Distributed under the Apache Software License 2.0. See [LICENSE](LICENSE) for more information.

## Support

Need help? Check out our documentation or open an issue on GitHub.

---

*Part of the Highway Workflow Engine family of resilience tools*