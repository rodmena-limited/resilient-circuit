Advanced Usage
==============

PostgreSQL Shared Storage
-------------------------

For distributed applications, Resilient Circuit supports PostgreSQL as a shared storage backend. This allows circuit breaker state to be synchronized across all instances of your application.

Configuration
~~~~~~~~~~~~~

First, install with PostgreSQL support:

.. code-block:: bash

   pip install resilient-circuit[postgres]

Create a ``.env`` file in your project root:

.. code-block:: ini

   RC_DB_HOST=localhost
   RC_DB_PORT=5432
   RC_DB_NAME=resilient_circuit_db
   RC_DB_USER=postgres
   RC_DB_PASSWORD=your_password

Set up the database table using the CLI:

.. code-block:: bash

   resilient-circuit-cli pg-setup

Once configured, the circuit breaker will automatically use PostgreSQL storage when environment variables are present:

.. code-block:: python

   from datetime import timedelta
   from fractions import Fraction
   from resilient_circuit import CircuitProtectorPolicy

   # This will automatically use PostgreSQL if RC_DB_* env vars are set
   circuit_breaker = CircuitProtectorPolicy(
       resource_key="payment_service",
       cooldown=timedelta(seconds=60),
       failure_limit=Fraction(5, 10)
   )

Custom Exception Handling
-------------------------

You can customize which exceptions should be considered failures:

.. code-block:: python

   def should_consider_failure(exception):
       # Only count network errors as failures
       return isinstance(exception, (ConnectionError, TimeoutError, requests.ConnectionError))

   circuit_breaker = CircuitProtectorPolicy(
       resource_key="my_service",
       should_handle=should_consider_failure
   )

   @circuit_breaker
   def my_function():
       # Only ConnectionError and TimeoutError will count as failures
       pass

Monitoring and Status Changes
-----------------------------

You can monitor circuit breaker status changes:

.. code-block:: python

   def on_status_change(policy, old_status, new_status):
       print(f"Circuit breaker {policy.resource_key} changed from {old_status.name} to {new_status.name}")

   circuit_breaker = CircuitProtectorPolicy(
       resource_key="my_service",
       on_status_change=on_status_change
   )

Accessing Circuit Breaker State
-------------------------------

You can access the current status and execution log:

.. code-block:: python

   circuit_breaker = CircuitProtectorPolicy(resource_key="my_service")

   # Check current status
   print(f"Current status: {circuit_breaker.status.name}")

   # Check execution log
   print(f"Execution log: {list(circuit_breaker.execution_log)}")

   # The execution_log buffer maintains success/failure record
   if circuit_breaker.status == CircuitState.OPEN:
       print("Circuit breaker is currently open - requests are blocked")
   else:
       # Execute call if not in OPEN status
       pass

Performance Considerations
--------------------------

When using PostgreSQL storage, consider these performance tips:

- The library uses row-level locking (``FOR UPDATE``) for atomic operations
- Proper indexing ensures fast lookups and updates
- The ``updated_at`` trigger only fires when values actually change
- Connection pooling is recommended for high-throughput applications