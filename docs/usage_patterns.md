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

### Simple Circuit Protector

For services that may occasionally fail:

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitProtectorPolicy

service_protector = CircuitProtectorPolicy(
    cooldown=timedelta(seconds=30),
    failure_limit=Fraction(2, 5)
)

@service_protector
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
from highway_circutbreaker import RetryWithBackoffPolicy, ExponentialDelay

service_retry = RetryWithBackoffPolicy(
    max_retries=3,
    backoff=ExponentialDelay(
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

### Database Operation with Circuit Protector

```python
import sqlite3
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitProtectorPolicy

db_protector = CircuitProtectorPolicy(
    cooldown=timedelta(seconds=60),
    failure_limit=Fraction(1, 5),
    should_handle=lambda e: isinstance(e, sqlite3.OperationalError)
)

@db_protector
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
from highway_circutbreaker import RetryWithBackoffPolicy

db_retry = RetryWithBackoffPolicy(
    max_retries=2,
    should_handle=lambda e: isinstance(e, (sqlite3.OperationalError, sqlite3.DatabaseError))
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

### External API with Both Circuit Protector and Retry

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import SafetyNet, RetryWithBackoffPolicy, CircuitProtectorPolicy

# Create resilient API client
api_safetynet = SafetyNet(
    policies=(
        # Apply retry first
        RetryWithBackoffPolicy(
            max_retries=2,
            backoff=ExponentialDelay(
                min_delay=timedelta(seconds=1),
                max_delay=timedelta(seconds=5),
                factor=2
            ),
            should_handle=lambda e: isinstance(e, requests.ConnectionError)
        ),
        # Then circuit protector
        CircuitProtectorPolicy(
            cooldown=timedelta(minutes=1),
            failure_limit=Fraction(3, 10),
            should_handle=lambda e: isinstance(e, (requests.ConnectionError, requests.Timeout))
        )
    )
)

@api_safetynet
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
from highway_circutbreaker import CircuitProtectorPolicy

def is_api_error_relevant(exc):
    """Check if the error is one we should handle"""
    if hasattr(exc, 'response'):
        return exc.response.status_code in [500, 502, 503, 504]
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))

oauth_protector = CircuitProtectorPolicy(
    cooldown=timedelta(minutes=5),
    failure_limit=Fraction(2, 5),
    should_handle=is_api_error_relevant
)

@oauth_protector
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

### Consumer with Circuit Protector

```python
from datetime import timedelta
from fractions import Fraction
from highway_circutbreaker import CircuitProtectorPolicy

def is_transient_error(exc):
    """Only handle transient errors, not permanent failures"""
    return (
        isinstance(exc, (ConnectionError, requests.Timeout)) or
        ("transient" in str(exc).lower())
    )

queue_consumer_protector = CircuitProtectorPolicy(
    cooldown=timedelta(seconds=30),
    failure_limit=Fraction(1, 3),
    should_handle=is_transient_error
)

@queue_consumer_protector
def process_queue_message(message):
    # Process the message
    try:
        # Parse and process the message
        data = message.json()
        result = handle_business_logic(data)
        # Acknowledge message
        return result
    except Exception as e:
        # Log the error but only handle transient errors in circuit protector
        print(f"Error processing message: {e}")
        raise  # Re-raise to let circuit protector handle it if needed
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
from highway_circutbreaker import CircuitProtectorPolicy, CircuitState

class CircuitProtectorMonitor:
    def __init__(self):
        self.state_transitions = []
        self.last_transition = datetime.now()
    
    def log_status_change(self, policy, old_status, new_status):
        transition_time = datetime.now()
        duration = transition_time - self.last_transition
        
        print(f"Circuit protector changed status: {old_status.name} -> {new_status.name}")
        print(f"Duration in {old_status.name} status: {duration}")
        
        self.status_transitions.append({
            'timestamp': transition_time,
            'old_status': old_status,
            'new_status': new_status,
            'duration': duration
        })
        
        # Alert on critical status changes
        if new_status == CircuitState.OPEN:
            self.send_alert(f"Circuit protector opened for service at {transition_time}")
        
        self.last_transition = transition_time
    
    def send_alert(self, message):
        # Send alert to monitoring system
        print(f"ALERT: {message}")

# Create monitor instance
monitor = CircuitProtectorMonitor()

# Create circuit protector with monitoring
monitored_protector = CircuitProtectorPolicy(
    cooldown=timedelta(seconds=60),
    failure_limit=Fraction(3, 10),
    on_status_change=monitor.log_status_change
)

@monitored_protector
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
from highway_circutbreaker import CircuitProtectorPolicy

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

def create_logged_circuit_protector(name):
    """Create a circuit protector with comprehensive logging"""
    
    def log_status_change(policy, old_status, new_status):
        logger.info(
            f"[{name}] Circuit protector status changed: {old_status.name} -> {new_status.name}"
        )
        # Log execution_log
        execution_log = list(policy.execution_log)
        logger.info(f"[{name}] Recent execution log: {execution_log}")
    
    return CircuitProtectorPolicy(
        cooldown=timedelta(seconds=30),
        failure_limit=Fraction(2, 5),
        on_status_change=log_status_change
    )

# Use the logged circuit protector
logged_protector = create_logged_circuit_protector("ExternalPaymentAPI")

@logged_protector
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

### Choose Circuit Protector When:
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