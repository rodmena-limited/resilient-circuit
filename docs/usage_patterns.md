# Highway Circuit Breaker - Usage Patterns

This document describes common usage patterns and real-world scenarios for Highway Circuit Breaker.

## Table of Contents
1. [Basic Service Calls](#basic-service-calls)
2. [Database Connections](#database-connections)
3. [API Integrations](#api-integrations)
4. [Message Queue Processing](#message-queue-processing)
5. [Batch Processing](#batch-processing)
6. [Monitoring and Logging](#monitoring-and-logging)

## Basic Service Calls

### Simple Circuit Breaker

For services that may occasionally fail:

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy

service_breaker = CircuitBreakerPolicy(
    cooldown=timedelta(seconds=30),
    failure_threshold=Fraction(2, 5)
)

@service_breaker
def call_external_service(data):
    # Your actual service call
    import requests
    response = requests.post("https://external-service/api", json=data)
    response.raise_for_status()
    return response.json()
```

### Service with Retry

For services that might have temporary issues:

```python
from datetime import timedelta
from highway_circutbreaker import RetryPolicy, Backoff

service_retry = RetryPolicy(
    max_retries=3,
    backoff=Backoff(
        min_delay=timedelta(seconds=1),
        max_delay=timedelta(seconds=10),
        factor=2
    )
)

@service_retry
def call_retryable_service(data):
    import requests
    response = requests.post("https://flaky-service/api", json=data)
    response.raise_for_status()
    return response.json()
```

## Database Connections

### Database Operation with Circuit Breaker

```python
import sqlite3
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy

db_breaker = CircuitBreakerPolicy(
    cooldown=timedelta(seconds=60),
    failure_threshold=Fraction(1, 5),
    handle=lambda e: isinstance(e, sqlite3.OperationalError)
)

@db_breaker
def get_user_data(user_id):
    conn = sqlite3.connect('mydb.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result
```

### Database with Retry

```python
from datetime import timedelta
from highway_circutbreaker import RetryPolicy

db_retry = RetryPolicy(
    max_retries=2,
    handle=lambda e: isinstance(e, (sqlite3.OperationalError, sqlite3.DatabaseError))
)

@db_retry
def update_user_data(user_id, data):
    conn = sqlite3.connect('mydb.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET data = ? WHERE id = ?", (data, user_id))
    conn.commit()
    conn.close()
```

## API Integrations

### External API with Both Circuit Breaker and Retry

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import Failsafe, RetryPolicy, CircuitBreakerPolicy

# Create resilient API client
api_failsafe = Failsafe(
    policies=(
        # Apply retry first
        RetryPolicy(
            max_retries=2,
            backoff=Backoff(
                min_delay=timedelta(seconds=1),
                max_delay=timedelta(seconds=5),
                factor=2
            ),
            handle=lambda e: isinstance(e, requests.ConnectionError)
        ),
        # Then circuit breaker
        CircuitBreakerPolicy(
            cooldown=timedelta(minutes=1),
            failure_threshold=Fraction(3, 10),
            handle=lambda e: isinstance(e, (requests.ConnectionError, requests.Timeout))
        )
    )
)

@api_failsafe
def fetch_external_data(query):
    import requests
    response = requests.get(
        f"https://api.external.com/data",
        params={'q': query},
        timeout=10
    )
    response.raise_for_status()
    return response.json()
```

### OAuth API with Specific Error Handling

```python
from datetime import timedelta
from highway_circutbreaker import CircuitBreakerPolicy

def is_api_error_relevant(exc):
    """Check if the error is one we should handle"""
    if hasattr(exc, 'response'):
        return exc.response.status_code in [500, 502, 503, 504]
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))

oauth_breaker = CircuitBreakerPolicy(
    cooldown=timedelta(minutes=5),
    failure_threshold=Fraction(2, 5),
    handle=is_api_error_relevant
)

@oauth_breaker
def call_oauth_protected_api():
    import requests
    # Refresh token logic here...
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.protected.com/data", headers=headers)
    if response.status_code == 401:
        # Refresh token and retry
        refresh_access_token()
        response = requests.get("https://api.protected.com/data", headers=headers)
    response.raise_for_status()
    return response.json()
```

## Message Queue Processing

### Consumer with Circuit Breaker

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy

def is_transient_error(exc):
    """Only handle transient errors, not permanent failures"""
    return (
        isinstance(exc, (ConnectionError, requests.Timeout)) or
        ("transient" in str(exc).lower())
    )

queue_consumer_breaker = CircuitBreakerPolicy(
    cooldown=timedelta(seconds=30),
    failure_threshold=Fraction(1, 3),
    handle=is_transient_error
)

@queue_consumer_breaker
def process_queue_message(message):
    # Process the message
    try:
        # Parse and process the message
        data = message.json()
        result = handle_business_logic(data)
        # Acknowledge message
        return result
    except Exception as e:
        # Log the error but only handle transient errors in circuit breaker
        print(f"Error processing message: {e}")
        raise  # Re-raise to let circuit breaker handle it if needed
```

## Batch Processing

### Batch Operation with Individual Item Retry

```python
from datetime import timedelta
from highway_circutbreaker import RetryPolicy

item_retry_policy = RetryPolicy(
    max_retries=1,
    handle=lambda e: isinstance(e, ValueError)  # Only retry value errors
)

def process_batch(items):
    results = []
    errors = []
    
    for item in items:
        try:
            # Apply retry policy to individual items
            processed_item = item_retry_policy(process_single_item)(item)
            results.append(processed_item)
        except Exception as e:
            errors.append((item, str(e)))
            # Continue processing other items
            continue
    
    return results, errors

def process_single_item(item):
    # Process a single item that might fail
    if item.get('unprocessible'):
        raise ValueError("Item cannot be processed")
    return {"id": item['id'], "status": "processed"}
```

## Monitoring and Logging

### Circuit Breaker with State Monitoring

```python
from datetime import datetime, timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy, CircuitBreakerState

class CircuitBreakerMonitor:
    def __init__(self):
        self.state_transitions = []
        self.last_transition = datetime.now()
    
    def log_state_change(self, policy, old_state, new_state):
        transition_time = datetime.now()
        duration = transition_time - self.last_transition
        
        print(f"Circuit breaker changed state: {old_state.name} -> {new_state.name}")
        print(f"Duration in {old_state.name} state: {duration}")
        
        self.state_transitions.append({
            'timestamp': transition_time,
            'old_state': old_state,
            'new_state': new_state,
            'duration': duration
        })
        
        # Alert on critical state changes
        if new_state == CircuitBreakerState.OPEN:
            self.send_alert(f"Circuit breaker opened for service at {transition_time}")
        
        self.last_transition = transition_time
    
    def send_alert(self, message):
        # Send alert to monitoring system
        print(f"ALERT: {message}")

# Create monitor instance
monitor = CircuitBreakerMonitor()

# Create circuit breaker with monitoring
monitored_breaker = CircuitBreakerPolicy(
    cooldown=timedelta(seconds=60),
    failure_threshold=Fraction(3, 10),
    on_state_change=monitor.log_state_change
)

@monitored_breaker
def monitored_service_call():
    # Service call with full monitoring
    import random
    if random.random() < 0.6:  # 60% failure rate for demo
        raise ConnectionError("Service unavailable")
    return "Success"
```

### Comprehensive Logging Configuration

```python
import logging
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitBreakerPolicy

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create handler and formatter
handler = logging.StreamHandler()
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

def create_logged_circuit_breaker(name):
    """Create a circuit breaker with comprehensive logging"""
    
    def log_state_change(policy, old_state, new_state):
        logger.info(
            f"[{name}] Circuit breaker state changed: {old_state.name} -> {new_state.name}"
        )
        # Log history
        history = list(policy.history)
        logger.info(f"[{name}] Recent execution history: {history}")
    
    return CircuitBreakerPolicy(
        cooldown=timedelta(seconds=30),
        failure_threshold=Fraction(2, 5),
        on_state_change=log_state_change
    )

# Use the logged circuit breaker
logged_breaker = create_logged_circuit_breaker("ExternalPaymentAPI")

@logged_breaker
def process_payment(amount, card_details):
    # Payment processing with comprehensive logging
    try:
        logger.info(f"Processing payment of ${amount}")
        # Actual payment processing
        result = execute_payment(amount, card_details)
        logger.info(f"Payment of ${amount} processed successfully")
        return result
    except Exception as e:
        logger.error(f"Payment processing failed: {str(e)}", exc_info=True)
        raise

def execute_payment(amount, card_details):
    # Payment processing implementation
    import random
    if random.random() < 0.3:  # 30% failure rate for demo
        raise ConnectionError("Payment gateway unavailable")
    return {"status": "success", "transaction_id": "12345"}
```

## Pattern Summary

### Choose Circuit Breaker When:
- You want to prevent cascading failures
- You have services that may go down temporarily
- You want to provide immediate failure responses during outages
- You need to monitor the health of dependencies

### Choose Retry When:
- Failures are likely to be temporary
- You want to improve user experience by hiding intermittent failures
- You need to implement exponential backoff for rate-limited APIs
- You're dealing with network flakiness

### Combine Both When:
- You're integrating with external services of uncertain reliability
- You want robust protection against various failure modes
- You need to maintain service availability under adverse conditions