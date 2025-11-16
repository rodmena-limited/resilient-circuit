Distributed Systems
===================

Overview
--------

Resilient Circuit is designed for distributed systems where multiple service instances need to coordinate failure handling. Using PostgreSQL as a shared storage backend, circuit breakers can synchronize state across all instances of your application.

Why Distributed Circuit Breakers?
----------------------------------

In a distributed architecture, you want:

**Coordinated Failure Handling**
   When one instance detects a failing external service, all instances should stop calling it immediately to prevent cascading failures.

**Shared State**
   Circuit breaker state (OPEN, CLOSED, HALF_OPEN) should be consistent across all instances.

**Persistence**
   State should survive instance restarts and deployments.

**Atomic Operations**
   State transitions must be thread-safe and race-condition-free.

Architecture Patterns
---------------------

Single Service, Multiple Instances
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The most common pattern: multiple instances of the same service share circuit breaker state.

.. code-block:: python

    # Instance 1 (Pod/Container A)
    from resilient_circuit import CircuitProtectorPolicy

    payment_cb = CircuitProtectorPolicy(
        resource_key="stripe_payment_api",  # Shared key
        cooldown=timedelta(minutes=5)
    )

    # Instance 2 (Pod/Container B)
    payment_cb = CircuitProtectorPolicy(
        resource_key="stripe_payment_api",  # Same key
        cooldown=timedelta(minutes=5)
    )

**Flow:**

1. Instance 1 calls Stripe API → fails repeatedly
2. Instance 1's circuit breaker opens → state saved to PostgreSQL
3. Instance 2 immediately sees OPEN state from PostgreSQL
4. Instance 2 stops calling Stripe API → prevents further failures

Multiple Services, Shared Resource
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Different services calling the same external resource:

.. code-block:: python

    # Payment Service
    payment_cb = CircuitProtectorPolicy(
        resource_key="external_fraud_check_api",
        cooldown=timedelta(minutes=2)
    )

    # Order Service
    order_cb = CircuitProtectorPolicy(
        resource_key="external_fraud_check_api",  # Same resource
        cooldown=timedelta(minutes=2)
    )

    # User Service
    user_cb = CircuitProtectorPolicy(
        resource_key="external_fraud_check_api",  # Same resource
        cooldown=timedelta(minutes=2)
    )

When any service detects fraud check API failures, all services stop calling it.

Per-Instance vs Shared Keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can mix local and shared circuit breakers:

.. code-block:: python

    # Local circuit breaker (per-instance)
    local_cb = CircuitProtectorPolicy(
        resource_key=f"local_cache_{instance_id}",  # Unique per instance
        storage=InMemoryStorage()  # In-memory only
    )

    # Shared circuit breaker (distributed)
    shared_cb = CircuitProtectorPolicy(
        resource_key="shared_external_api",  # Same across instances
        # Automatically uses PostgreSQL if configured
    )

Use Cases
---------

Microservices Architecture
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Scenario**: E-commerce platform with multiple microservices

.. code-block:: python

    # All services configure the same circuit breakers
    shared_resources = {
        "payment_gateway": CircuitProtectorPolicy(
            resource_key="payment_gateway",
            cooldown=timedelta(minutes=5),
            failure_limit=Fraction(3, 10)
        ),
        "inventory_service": CircuitProtectorPolicy(
            resource_key="inventory_service",
            cooldown=timedelta(seconds=30),
            failure_limit=Fraction(2, 5)
        ),
        "shipping_api": CircuitProtectorPolicy(
            resource_key="shipping_api",
            cooldown=timedelta(minutes=2),
            failure_limit=Fraction(1, 3)
        ),
    }

    # In Order Service
    @shared_resources["payment_gateway"]
    def charge_payment(order):
        # Payment processing
        pass

    # In Fulfillment Service
    @shared_resources["payment_gateway"]
    def refund_payment(order):
        # Refund processing
        pass

Both services benefit from shared circuit breaker state.

Kubernetes Deployments
~~~~~~~~~~~~~~~~~~~~~~

**Scenario**: Kubernetes deployment with auto-scaling

.. code-block:: yaml

    # deployment.yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: payment-service
    spec:
      replicas: 5  # 5 instances
      template:
        spec:
          containers:
          - name: payment-service
            image: payment-service:latest
            env:
            - name: RC_DB_HOST
              value: postgresql.default.svc.cluster.local
            - name: RC_DB_NAME
              value: resilient_circuit_db
            - name: RC_DB_USER
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: username
            - name: RC_DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: password

.. code-block:: python

    # payment_service/main.py
    from resilient_circuit import CircuitProtectorPolicy

    # All 5 replicas share this circuit breaker state
    external_api_cb = CircuitProtectorPolicy(
        resource_key="external_kyc_api",
        cooldown=timedelta(minutes=10)
    )

When Kubernetes scales to 10 replicas, all instances automatically share state.

Serverless Functions
~~~~~~~~~~~~~~~~~~~~

**Scenario**: AWS Lambda or Google Cloud Functions

.. code-block:: python

    import os
    from resilient_circuit import CircuitProtectorPolicy

    # Lambda function
    def lambda_handler(event, context):
        # Circuit breaker persists across invocations via PostgreSQL
        cb = CircuitProtectorPolicy(
            resource_key="third_party_api",
            cooldown=timedelta(minutes=5)
        )

        @cb
        def call_third_party():
            # API call
            pass

        result = call_third_party()
        return result

Multiple Lambda invocations share the same circuit breaker state through PostgreSQL.

Multi-Region Deployments
~~~~~~~~~~~~~~~~~~~~~~~~~

**Scenario**: Services deployed across multiple regions

.. code-block:: python

    # us-east-1 region
    cb_east = CircuitProtectorPolicy(
        resource_key="global_payment_processor",
        # Connected to PostgreSQL primary in us-east-1
    )

    # eu-west-1 region
    cb_eu = CircuitProtectorPolicy(
        resource_key="global_payment_processor",
        # Connected to PostgreSQL replica in eu-west-1
    )

**Note**: For multi-region setups, consider PostgreSQL replication latency and eventual consistency.

State Synchronization
---------------------

How It Works
~~~~~~~~~~~~

1. **State Read**: Circuit breaker loads current state from PostgreSQL on initialization
2. **State Update**: Every state change is immediately persisted to PostgreSQL
3. **Atomic Operations**: PostgreSQL row-level locking ensures atomicity
4. **New Instance**: When a new instance starts, it loads the latest state

State Transition Example
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Time T0: All instances see CLOSED state
    # Instance 1, 2, 3 → CLOSED

    # Time T1: Instance 1 experiences failures
    # Instance 1 → Executes 10 calls, 6 fail
    # Instance 1 → Transitions to OPEN
    # Instance 1 → Saves state to PostgreSQL

    # Time T2: Instance 2 checks state before next call
    # Instance 2 → Loads state from PostgreSQL
    # Instance 2 → Sees OPEN state
    # Instance 2 → Blocks call without executing

    # Time T3: After cooldown expires
    # Instance 3 → First to attempt call after cooldown
    # Instance 3 → Transitions to HALF_OPEN
    # Instance 3 → Saves state to PostgreSQL
    # Instance 3 → Attempts call

    # Time T4: Call succeeds
    # Instance 3 → Transitions to CLOSED
    # Instance 3 → Saves state to PostgreSQL
    # All instances → See CLOSED state on next check

Concurrency Handling
~~~~~~~~~~~~~~~~~~~~

PostgreSQL's ``FOR UPDATE`` locks prevent race conditions:

.. code-block:: sql

    -- Internal query used by Resilient Circuit
    SELECT state, failure_count, open_until
    FROM rc_circuit_breakers
    WHERE resource_key = 'payment_api'
    FOR UPDATE;  -- Locks the row

This ensures only one instance can transition state at a time.

Performance Optimization
------------------------

Circuit Breaker Caching
~~~~~~~~~~~~~~~~~~~~~~~~

Reuse circuit breaker instances:

.. code-block:: python

    # Good: Create once, reuse many times
    payment_cb = CircuitProtectorPolicy(
        resource_key="payment_service"
    )

    @payment_cb
    def process_payment():
        pass

    # Call multiple times with same instance
    for order in orders:
        process_payment()

    # Bad: Creating new instance on every call
    def process_payment():
        cb = CircuitProtectorPolicy(
            resource_key="payment_service"
        )
        # ...

Lazy Loading
~~~~~~~~~~~~

Load state from PostgreSQL only when needed:

.. code-block:: python

    from resilient_circuit import CircuitProtectorPolicy
    from resilient_circuit.storage import create_storage

    # Initialize storage once
    storage = create_storage()

    # Share storage across circuit breakers
    cb1 = CircuitProtectorPolicy(
        resource_key="api_1",
        storage=storage
    )

    cb2 = CircuitProtectorPolicy(
        resource_key="api_2",
        storage=storage
    )

Connection Pooling
~~~~~~~~~~~~~~~~~~

For high-throughput applications, consider PostgreSQL connection pooling:

.. code-block:: python

    # Using pgbouncer or similar
    # Set RC_DB_HOST to pgbouncer address
    export RC_DB_HOST=pgbouncer.internal.svc.cluster.local
    export RC_DB_PORT=6432

Monitoring and Observability
-----------------------------

Real-Time Monitoring
~~~~~~~~~~~~~~~~~~~~

Query circuit breaker state across all instances:

.. code-block:: sql

    -- Dashboard query: Current state of all circuit breakers
    SELECT
        resource_key,
        state,
        failure_count,
        CASE
            WHEN state = 'OPEN' THEN
                EXTRACT(EPOCH FROM (open_until - NOW()))
            ELSE 0
        END as seconds_until_halfopen,
        updated_at
    FROM rc_circuit_breakers
    ORDER BY updated_at DESC;

Alerting
~~~~~~~~

Set up alerts for critical circuit breakers:

.. code-block:: sql

    -- Alert: Payment service circuit breaker opened
    SELECT resource_key, state, updated_at
    FROM rc_circuit_breakers
    WHERE resource_key = 'payment_service'
      AND state = 'OPEN'
      AND updated_at > NOW() - INTERVAL '5 minutes';

Metrics Collection
~~~~~~~~~~~~~~~~~~

Collect metrics for monitoring systems:

.. code-block:: python

    from resilient_circuit import CircuitProtectorPolicy

    def status_change_callback(policy, old_state, new_state):
        # Send metric to Prometheus/DataDog/etc.
        metrics.increment(
            'circuit_breaker.state_change',
            tags=[
                f'resource:{policy.resource_key}',
                f'old_state:{old_state.value}',
                f'new_state:{new_state.value}'
            ]
        )

    cb = CircuitProtectorPolicy(
        resource_key="critical_api",
        on_status_change=status_change_callback
    )

Best Practices
--------------

1. **Use Consistent Resource Keys**

   Ensure all instances use identical ``resource_key`` values.

2. **Configure Appropriate Timeouts**

   Set cooldown periods that match your service's recovery time.

3. **Test Failover Scenarios**

   Verify circuit breakers work correctly during:

   * PostgreSQL downtime (should fallback to in-memory)
   * Network partitions
   * Instance scaling events

4. **Monitor Database Performance**

   Circuit breakers add database load. Monitor:

   * Connection count
   * Query latency
   * Lock contention

5. **Plan for PostgreSQL Maintenance**

   Circuit breakers gracefully degrade to in-memory storage if PostgreSQL is unavailable.

Troubleshooting
---------------

Instances Not Syncing
~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: Different instances show different circuit states

**Solutions**:

1. Verify all instances connect to the same PostgreSQL database
2. Check ``resource_key`` is identical across instances
3. Ensure network connectivity between instances and database
4. Check for clock skew across instances

High Database Load
~~~~~~~~~~~~~~~~~~

**Symptom**: PostgreSQL CPU or connection count high

**Solutions**:

1. Add connection pooling (pgbouncer)
2. Increase PostgreSQL connection limits
3. Optimize indexes (already created by CLI)
4. Use fewer circuit breakers or longer cache times

State Not Persisting
~~~~~~~~~~~~~~~~~~~~

**Symptom**: Circuit breaker state resets after instance restart

**Solutions**:

1. Verify PostgreSQL storage is configured (check RC_DB_* env vars)
2. Check circuit breaker is using PostgreSQL, not in-memory storage
3. Verify database permissions allow writes
4. Check application logs for storage errors

See Also
--------

* :doc:`postgresql` - PostgreSQL storage guide
* :doc:`quickstart` - Getting started
* :doc:`advanced` - Advanced patterns
* :doc:`api` - API reference
