Quick Start
===========

Basic Usage
-----------

The Highway Circuit Breaker library provides a simple way to protect your functions from failures:

.. code-block:: python

   from datetime import timedelta
   from fractions import Fraction
   from highway_circutbreaker import CircuitProtectorPolicy

   # Create a circuit protector that trips after 3 failures in 10 attempts
   protector = CircuitProtectorPolicy(
       resource_key="my_service",
       failure_limit=Fraction(3, 10),  # 3 out of 10 failures
       cooldown=timedelta(seconds=30)  # 30-second cooldown
   )

   @protector
   def unreliable_service_call():
       # Your potentially failing external service call
       import random
       if random.random() < 0.7:  # 70% failure rate
           raise Exception("Service temporarily unavailable")
       return "Success!"

   # The protector will allow calls until failure threshold is met,
   # then transition to OPEN state, blocking calls for the cooldown period

Advanced Usage
--------------

You can customize the circuit breaker behavior with various options:

.. code-block:: python

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
       resource_key="my_service",
       cooldown=timedelta(minutes=1),                      # 1-minute cooldown
       failure_limit=Fraction(3, 10),                     # Trip after 30% failure rate
       success_limit=Fraction(5, 5),                      # Close after 5 consecutive successes
       should_handle=custom_exception_handler,            # Custom exception filter
       on_status_change=status_change_handler             # Status change listener
   )

Retry Pattern
-------------

You can also use the retry pattern with exponential backoff:

.. code-block:: python

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

Combining Patterns
------------------

You can combine circuit breaker and retry patterns using SafetyNet:

.. code-block:: python

   from highway_circutbreaker import SafetyNet, CircuitProtectorPolicy, RetryWithBackoffPolicy

   # Combine both patterns using SafetyNet
   safety_net = SafetyNet(
       policies=(
           RetryWithBackoffPolicy(max_retries=2),
           CircuitProtectorPolicy(resource_key="my_service", failure_limit=Fraction(2, 5))
       )
   )

   @safety_net
   def resilient_external_api_call():
       # This will first retry, then circuit-protect if needed
       pass