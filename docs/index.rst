.. Resilient Circuit documentation master file

Welcome to Resilient Circuit!
==============================

**Resilient Circuit** is a powerful resilience library for building fault-tolerant Python applications. It provides implementations of the **Circuit Breaker** and **Retry** patterns, with optional **PostgreSQL support** for distributed systems.

Perfect for microservices, distributed systems, and any application that needs to gracefully handle external service failures.

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickstart

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   advanced
   postgresql
   distributed
   cli

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api
   changelog

Key Features
------------

🔒 **Circuit Breaker Pattern**
   Prevents cascading failures by stopping calls to failing services

🔄 **Retry with Backoff**
   Automatically retries failed operations with exponential or fixed backoff

🗄️ **PostgreSQL Storage**
   Optional distributed state management for multi-instance deployments

🎯 **Composable Policies**
   Chain multiple resilience patterns together with SafetyNet

🐍 **Pythonic API**
   Clean decorator-based syntax that feels natural in Python

📊 **State Monitoring**
   Track circuit breaker state and execution history

⚡ **Production Ready**
   Battle-tested with comprehensive test coverage

Quick Example
-------------

.. code-block:: python

    from datetime import timedelta
    from fractions import Fraction
    from resilient_circuit import CircuitProtectorPolicy

    # Create a circuit breaker
    circuit_breaker = CircuitProtectorPolicy(
        resource_key="payment_service",
        cooldown=timedelta(seconds=30),
        failure_limit=Fraction(3, 10)  # Trip after 30% failure rate
    )

    @circuit_breaker
    def process_payment(amount):
        # Your payment logic here
        return payment_api.charge(amount)

For distributed systems with PostgreSQL:

.. code-block:: python

    # Set environment variables
    # RC_DB_HOST=localhost
    # RC_DB_NAME=resilient_circuit_db
    # RC_DB_PASSWORD=secret

    # All instances share the same circuit breaker state!
    circuit_breaker = CircuitProtectorPolicy(
        resource_key="shared_payment_service"
    )

Why Resilient Circuit?
-----------------------

**For Distributed Systems**

When you have multiple instances of a service, you want them all to coordinate failure handling. Resilient Circuit's PostgreSQL backend ensures all instances see the same circuit breaker state, preventing cascading failures across your entire infrastructure.

**Production-Grade Reliability**

- ✅ **91/91 tests passing** (100% test coverage)
- ✅ Works with and without PostgreSQL
- ✅ Automatic fallback to in-memory storage
- ✅ Thread-safe operations with PostgreSQL row locking
- ✅ Comprehensive error handling

**Developer Friendly**

- Clean, intuitive API
- Excellent documentation
- Type hints throughout
- Clear error messages

Use Cases
---------

**Microservices**
   Coordinate circuit breakers across service instances

**External APIs**
   Protect against third-party service outages

**Database Calls**
   Handle temporary database connection issues

**Message Queues**
   Gracefully handle queue connection failures

**Cloud Services**
   Resilience for AWS, GCP, Azure service calls

Installation
------------

Basic installation:

.. code-block:: bash

    pip install resilient-circuit

With PostgreSQL support for distributed systems:

.. code-block:: bash

    pip install resilient-circuit[postgres]

What's Next?
------------

- **New to Resilient Circuit?** Start with the :doc:`quickstart` guide
- **Setting up PostgreSQL?** See the :doc:`postgresql` guide
- **Building distributed systems?** Check out :doc:`distributed`
- **Need API details?** View the :doc:`api` reference

Community
---------

- **GitHub**: `github.com/rodmena-limited/resilient-circuit <https://github.com/rodmena-limited/resilient-circuit>`_
- **Issues**: `Report bugs or request features <https://github.com/rodmena-limited/resilient-circuit/issues>`_
- **PyPI**: `pypi.org/project/resilient-circuit <https://pypi.org/project/resilient-circuit>`_

License
-------

Resilient Circuit is distributed under the Apache Software License 2.0.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
