This is a resilient circuit breaker library for distributed systems.

Package name: resilient-circuit
Python module: resilient_circuit

The library has full PostgreSQL compatibility as an optional feature for distributed state management.
Database name: resilient_circuit_db
Environment variables: RC_DB_HOST, RC_DB_PORT, RC_DB_NAME, RC_DB_USER, RC_DB_PASSWORD

Features:
- Circuit breaker pattern with PostgreSQL persistence
- Automatic fallback to in-memory storage if no database connection
- Retry with exponential backoff
- Safety net for combining multiple protection policies
- Full test coverage with and without PostgreSQL

All 91 tests pass with and without PostgreSQL connection.
Ready for PyPI deployment.
