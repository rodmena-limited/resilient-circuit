PostgreSQL Storage for Distributed Systems
==========================================

Overview
--------

Resilient Circuit supports PostgreSQL as an optional storage backend for circuit breaker state. This enables distributed applications to share circuit breaker state across multiple instances, ensuring coordinated failure handling in distributed systems.

Why PostgreSQL Storage?
-----------------------

In distributed systems, circuit breakers need to coordinate state across multiple service instances:

* **Shared State**: All instances see the same circuit breaker status
* **Persistence**: State survives application restarts
* **Atomic Operations**: Thread-safe updates using PostgreSQL row-level locking
* **Monitoring**: Query circuit breaker state directly from the database
* **Scalability**: Supports high-concurrency applications

Installation
------------

Install Resilient Circuit with PostgreSQL support:

.. code-block:: bash

    pip install resilient-circuit[postgres]

This installs the required dependencies:

* ``psycopg[binary]>=3.1.0`` - PostgreSQL adapter
* ``python-dotenv>=1.0.0`` - Environment variable management

Database Setup
--------------

1. Create PostgreSQL Database
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a PostgreSQL database for circuit breaker state:

.. code-block:: bash

    createdb -h localhost -U postgres resilient_circuit_db

Or using SQL:

.. code-block:: sql

    CREATE DATABASE resilient_circuit_db;

2. Configure Environment Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a ``.env`` file in your project root:

.. code-block:: bash

    RC_DB_HOST=localhost
    RC_DB_PORT=5432
    RC_DB_NAME=resilient_circuit_db
    RC_DB_USER=postgres
    RC_DB_PASSWORD=your_password

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 50 15 15

   * - Variable
     - Description
     - Default
     - Required
   * - RC_DB_HOST
     - PostgreSQL host address
     - —
     - Yes
   * - RC_DB_PORT
     - PostgreSQL port number
     - 5432
     - No
   * - RC_DB_NAME
     - Database name
     - resilient_circuit_db
     - No
   * - RC_DB_USER
     - Database username
     - postgres
     - No
   * - RC_DB_PASSWORD
     - Database password
     - —
     - Yes

3. Initialize Database Tables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the CLI to create tables and indexes:

.. code-block:: bash

    resilient-circuit pg-setup --yes

This command creates:

* ``rc_circuit_breakers`` table
* Indexes for performance optimization
* Triggers for automatic timestamp updates

CLI Options
~~~~~~~~~~~

.. code-block:: bash

    # Interactive mode (asks for confirmation)
    resilient-circuit pg-setup

    # Auto-confirm mode
    resilient-circuit pg-setup --yes

    # Dry run (show what would be done)
    resilient-circuit pg-setup --dry-run

Database Schema
---------------

Table Structure
~~~~~~~~~~~~~~~

.. code-block:: sql

    CREATE TABLE rc_circuit_breakers (
        resource_key VARCHAR(255) PRIMARY KEY,
        state VARCHAR(50) NOT NULL,
        failure_count INTEGER NOT NULL DEFAULT 0,
        open_until TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

Indexes
~~~~~~~

* ``rc_circuit_breakers_pkey`` - Primary key on resource_key
* ``idx_rc_circuit_breakers_state`` - Index on state column
* ``idx_rc_circuit_breakers_open_until`` - Index on open_until timestamp
* ``idx_rc_circuit_breakers_key_state`` - Composite index on (resource_key, state)
* ``idx_rc_circuit_breakers_state_updated`` - Index on (state, updated_at DESC)

Usage
-----

Basic Usage with PostgreSQL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once configured, circuit breakers automatically use PostgreSQL storage:

.. code-block:: python

    from datetime import timedelta
    from fractions import Fraction
    from resilient_circuit import CircuitProtectorPolicy

    # Automatically uses PostgreSQL if RC_DB_* env vars are set
    circuit_breaker = CircuitProtectorPolicy(
        resource_key="payment_service",
        cooldown=timedelta(seconds=60),
        failure_limit=Fraction(5, 10)  # 50% failure rate
    )

    @circuit_breaker
    def process_payment():
        # Your payment processing logic
        pass

Distributed System Example
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Multiple services sharing the same circuit breaker:

.. code-block:: python

    # Service Instance 1 (Server A)
    from resilient_circuit import CircuitProtectorPolicy

    cb1 = CircuitProtectorPolicy(
        resource_key="shared_external_api",
        cooldown=timedelta(minutes=5)
    )

    # Service Instance 2 (Server B)
    # Shares the same state through PostgreSQL
    cb2 = CircuitProtectorPolicy(
        resource_key="shared_external_api",  # Same resource_key
        cooldown=timedelta(minutes=5)
    )

    # When cb1 opens the circuit, cb2 immediately sees the OPEN state

Explicit Storage Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can explicitly specify the storage backend:

.. code-block:: python

    from resilient_circuit.storage import PostgresStorage, InMemoryStorage

    # Explicit PostgreSQL storage
    pg_storage = PostgresStorage(
        "host=localhost port=5432 dbname=resilient_circuit_db "
        "user=postgres password=secret"
    )

    circuit_breaker = CircuitProtectorPolicy(
        resource_key="my_service",
        storage=pg_storage
    )

    # Or use in-memory storage
    memory_storage = InMemoryStorage()

    circuit_breaker = CircuitProtectorPolicy(
        resource_key="my_service",
        storage=memory_storage
    )

Monitoring
----------

Query Circuit Breaker State
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use SQL to monitor circuit breaker status:

.. code-block:: sql

    -- View all circuit breakers and their status
    SELECT resource_key, state, failure_count, open_until, updated_at
    FROM rc_circuit_breakers
    ORDER BY updated_at DESC;

    -- Find all open circuit breakers
    SELECT resource_key, open_until, updated_at
    FROM rc_circuit_breakers
    WHERE state = 'OPEN';

    -- Check failure counts
    SELECT resource_key, failure_count, state
    FROM rc_circuit_breakers
    WHERE state = 'CLOSED'
    ORDER BY failure_count DESC;

    -- Monitor circuit breaker transitions
    SELECT resource_key, state, updated_at
    FROM rc_circuit_breakers
    WHERE updated_at > NOW() - INTERVAL '1 hour'
    ORDER BY updated_at DESC;

Fallback Behavior
-----------------

Automatic Fallback to In-Memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Resilient Circuit automatically falls back to in-memory storage if:

* PostgreSQL environment variables are not set
* Database connection fails
* Database is unavailable

.. code-block:: python

    # No RC_DB_* env vars → Uses InMemoryStorage
    circuit_breaker = CircuitProtectorPolicy(
        resource_key="my_service"
    )

The fallback is transparent and logged appropriately.

Performance Considerations
--------------------------

Connection Pooling
~~~~~~~~~~~~~~~~~~

PostgreSQL storage creates new connections per operation. For high-performance applications, consider:

* Connection pooling at the application level
* Caching circuit breaker instances
* Using appropriate PostgreSQL configuration

.. code-block:: python

    # Reuse circuit breaker instances
    payment_cb = CircuitProtectorPolicy(
        resource_key="payment_service"
    )

    # Use the same instance for multiple calls
    payment_cb(process_payment_1)()
    payment_cb(process_payment_2)()

Latency
~~~~~~~

PostgreSQL operations add approximately 1-5ms latency compared to in-memory storage. This is acceptable for most circuit breaker use cases since:

* Circuit breakers are evaluated on every call anyway
* The distributed coordination benefits outweigh the small latency cost
* Failed calls typically take much longer than database operations

Best Practices
--------------

1. **Use Meaningful Resource Keys**

   .. code-block:: python

       # Good: Descriptive resource keys
       CircuitProtectorPolicy(resource_key="stripe_payment_api")
       CircuitProtectorPolicy(resource_key="user_service_grpc")

       # Bad: Generic resource keys
       CircuitProtectorPolicy(resource_key="api_1")

2. **Share Resource Keys Across Instances**

   For distributed systems, use the same ``resource_key`` across all service instances.

3. **Monitor Database Size**

   The table size grows with the number of unique resource keys. Periodically clean up unused entries:

   .. code-block:: sql

       DELETE FROM rc_circuit_breakers
       WHERE updated_at < NOW() - INTERVAL '30 days';

4. **Configure Appropriate Indexes**

   The CLI creates optimal indexes. Don't remove them unless you have specific performance reasons.

5. **Test Fallback Behavior**

   Ensure your application works correctly when PostgreSQL is unavailable.

Troubleshooting
---------------

Connection Errors
~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Check logs for connection errors
    import logging
    logging.basicConfig(level=logging.INFO)

Common issues:

* Wrong credentials → Check RC_DB_PASSWORD
* Database doesn't exist → Run ``createdb resilient_circuit_db``
* Host unreachable → Check RC_DB_HOST and network connectivity

State Not Syncing
~~~~~~~~~~~~~~~~~

If multiple instances don't see the same state:

1. Verify all instances use the **same** ``resource_key``
2. Check all instances connect to the **same** database
3. Verify PostgreSQL is running and accessible
4. Check for network partitions or firewall issues

Table Not Found
~~~~~~~~~~~~~~~

If you see "relation 'rc_circuit_breakers' does not exist":

.. code-block:: bash

    # Run the setup command
    resilient-circuit pg-setup --yes

See Also
--------

* :doc:`quickstart` - Getting started guide
* :doc:`advanced` - Advanced usage patterns
* :doc:`cli` - CLI reference
* :doc:`api` - API documentation
