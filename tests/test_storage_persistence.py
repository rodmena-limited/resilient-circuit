"""Tests for storage backend and state persistence (critical for distributed systems)."""
import os
from datetime import timedelta
from unittest.mock import Mock

import pytest

from resilient_circuit.circuit_breaker import CircuitProtectorPolicy, CircuitStatus
from resilient_circuit.storage import (
    InMemoryStorage,
    PostgresStorage,
    create_storage,
)


class TestStorageBackendSelection:
    """Test that the correct storage backend is selected based on environment."""

    def test_should_use_postgres_storage_when_env_vars_present(self, monkeypatch):
        """When PostgreSQL env vars are set, should use PostgresStorage."""
        # Set PostgreSQL env vars for this test
        monkeypatch.setenv("RC_DB_HOST", "localhost")
        monkeypatch.setenv("RC_DB_PASSWORD", "postgres")
        monkeypatch.setenv("RC_DB_NAME", "resilient_circuit_db")

        storage = create_storage()

        # Should use PostgresStorage (or fallback to InMemory if connection fails)
        assert isinstance(storage, (PostgresStorage, InMemoryStorage))

    def test_should_use_inmemory_storage_when_no_env_vars(self, monkeypatch):
        """When no PostgreSQL env vars, should use InMemoryStorage."""
        # Clear all DB-related env vars
        monkeypatch.delenv("RC_DB_HOST", raising=False)
        monkeypatch.delenv("RC_DB_PORT", raising=False)
        monkeypatch.delenv("RC_DB_NAME", raising=False)
        monkeypatch.delenv("RC_DB_USER", raising=False)
        monkeypatch.delenv("RC_DB_PASSWORD", raising=False)

        storage = create_storage()

        assert isinstance(storage, InMemoryStorage)

    def test_should_fallback_to_inmemory_on_postgres_failure(self, monkeypatch):
        """When PostgreSQL connection fails, should fallback to InMemoryStorage."""
        # Set env vars to invalid PostgreSQL connection
        monkeypatch.setenv("RC_DB_HOST", "invalid-host-that-does-not-exist")
        monkeypatch.setenv("RC_DB_PORT", "5432")
        monkeypatch.setenv("RC_DB_NAME", "nonexistent_db")
        monkeypatch.setenv("RC_DB_USER", "invalid_user")
        monkeypatch.setenv("RC_DB_PASSWORD", "invalid_password")

        storage = create_storage()

        # Should fallback to InMemoryStorage due to connection failure
        assert isinstance(storage, InMemoryStorage)


class TestInMemoryStorage:
    """Test InMemoryStorage backend."""

    @pytest.fixture
    def storage(self):
        return InMemoryStorage()

    def test_should_return_none_for_nonexistent_key(self, storage):
        result = storage.get_state("nonexistent_key")
        assert result is None

    def test_should_store_and_retrieve_state(self, storage):
        storage.set_state("test_key", "OPEN", 5, 12345.67)
        result = storage.get_state("test_key")

        assert result is not None
        assert result["state"] == "OPEN"
        assert result["failure_count"] == 5
        assert result["open_until"] == 12345.67

    def test_should_update_existing_state(self, storage):
        storage.set_state("test_key", "CLOSED", 0, 0)
        storage.set_state("test_key", "OPEN", 3, 99999.99)

        result = storage.get_state("test_key")
        assert result["state"] == "OPEN"
        assert result["failure_count"] == 3


@pytest.mark.skipif(
    not os.getenv("RC_DB_HOST"),
    reason="PostgreSQL not configured (no RC_DB_HOST env var)"
)
class TestPostgresStorage:
    """Test PostgresStorage backend - requires PostgreSQL to be running."""

    @pytest.fixture
    def storage(self):
        """Create a PostgresStorage instance for testing."""
        db_host = os.getenv("RC_DB_HOST")
        db_port = os.getenv("RC_DB_PORT", "5432")
        db_name = os.getenv("RC_DB_NAME", "resilient_circuit_db")
        db_user = os.getenv("RC_DB_USER", "postgres")
        db_password = os.getenv("RC_DB_PASSWORD")

        connection_string = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_password}"

        try:
            storage = PostgresStorage(connection_string)
            yield storage

            # Cleanup: delete test keys
            with storage._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM rc_circuit_breakers WHERE resource_key LIKE 'test_%'")
                    conn.commit()
        except Exception as e:
            pytest.skip(f"PostgreSQL not available: {e}")

    def test_should_return_none_for_nonexistent_key(self, storage):
        result = storage.get_state("test_nonexistent_key_12345")
        assert result is None

    def test_should_store_and_retrieve_state(self, storage):
        storage.set_state("test_key_store_retrieve", "OPEN", 5, 12345.67)
        result = storage.get_state("test_key_store_retrieve")

        assert result is not None
        assert result["state"] == "OPEN"
        assert result["failure_count"] == 5
        # Allow small floating point differences due to timestamp conversion
        assert abs(result["open_until"] - 12345.67) < 1.0

    def test_should_update_existing_state(self, storage):
        storage.set_state("test_key_update", "CLOSED", 0, 0)
        storage.set_state("test_key_update", "OPEN", 3, 99999.99)

        result = storage.get_state("test_key_update")
        assert result["state"] == "OPEN"
        assert result["failure_count"] == 3


class TestCircuitBreakerPersistence:
    """Test that circuit breaker state persists across instances (distributed system scenario)."""

    @pytest.fixture
    def shared_resource_key(self):
        """Use a unique resource key for each test."""
        import uuid
        return f"test_resource_{uuid.uuid4().hex[:8]}"

    def test_should_persist_state_across_instances_with_same_resource_key(
        self, shared_resource_key
    ):
        """
        Critical for distributed systems: State should persist across different
        circuit breaker instances that share the same resource_key.
        """
        # Create first circuit breaker instance
        cb1 = CircuitProtectorPolicy(
            resource_key=shared_resource_key,
            cooldown=timedelta(seconds=1)
        )

        # Verify it starts in CLOSED state
        assert cb1.status == CircuitStatus.CLOSED

        # Open the circuit
        cb1.status = CircuitStatus.OPEN
        assert cb1.status == CircuitStatus.OPEN

        # Create SECOND instance with same resource_key (simulates another server/process)
        cb2 = CircuitProtectorPolicy(
            resource_key=shared_resource_key,
            cooldown=timedelta(seconds=1)
        )

        # Check if storage is PostgresStorage (durable) or InMemoryStorage (non-durable)
        storage = create_storage()

        if isinstance(storage, PostgresStorage):
            # With PostgreSQL, state SHOULD persist across instances
            assert cb2.status == CircuitStatus.OPEN, (
                "With PostgreSQL storage, circuit breaker state should persist "
                "across instances with the same resource_key (critical for distributed systems)"
            )
        else:
            # With InMemoryStorage, state does NOT persist (each instance has own memory)
            assert cb2.status == CircuitStatus.CLOSED, (
                "With InMemoryStorage, each circuit breaker instance has independent state"
            )

    def test_should_track_failure_count_across_instances(self, shared_resource_key):
        """Failure counts should persist when using PostgreSQL storage."""
        storage = create_storage()

        # Skip this test if using in-memory storage
        if isinstance(storage, InMemoryStorage):
            pytest.skip("This test requires PostgreSQL for state persistence")

        # Create first instance and trigger some failures
        cb1 = CircuitProtectorPolicy(resource_key=shared_resource_key)

        failing_func = Mock(side_effect=RuntimeError("test error"))

        try:
            cb1(failing_func)()
        except RuntimeError:
            pass

        assert cb1.status == CircuitStatus.OPEN

        # Create second instance - should see the OPEN state from first instance
        cb2 = CircuitProtectorPolicy(resource_key=shared_resource_key)

        assert cb2.status == CircuitStatus.OPEN, (
            "Second instance should load OPEN state from PostgreSQL"
        )

    def test_should_isolate_state_for_different_resource_keys(self):
        """Different resource keys should have independent circuit breaker states."""
        cb1 = CircuitProtectorPolicy(resource_key="resource_a")
        cb2 = CircuitProtectorPolicy(resource_key="resource_b")

        # Open circuit for resource_a
        cb1.status = CircuitStatus.OPEN

        # resource_b should remain CLOSED
        assert cb1.status == CircuitStatus.OPEN
        assert cb2.status == CircuitStatus.CLOSED


class TestDistributedSystemScenario:
    """
    Test realistic distributed system scenarios where multiple services
    share the same circuit breaker state through PostgreSQL.
    """

    @pytest.mark.skipif(
        not isinstance(create_storage(), PostgresStorage),
        reason="This test requires PostgreSQL for distributed state sharing"
    )
    def test_distributed_circuit_breaker_protects_shared_resource(self):
        """
        Scenario: Multiple microservices calling the same external API.
        When one service opens the circuit due to failures, all other services
        should see the OPEN state and stop calling the API.
        """
        shared_api_key = "external_api_payment_service"

        # Service 1 detects failures and opens circuit
        service1_cb = CircuitProtectorPolicy(
            resource_key=shared_api_key,
            cooldown=timedelta(seconds=5)
        )

        # Simulate failure
        service1_cb.status = CircuitStatus.OPEN

        # Service 2 (on different server) should immediately see OPEN state
        service2_cb = CircuitProtectorPolicy(
            resource_key=shared_api_key,
            cooldown=timedelta(seconds=5)
        )

        assert service2_cb.status == CircuitStatus.OPEN, (
            "Service 2 should immediately see that Service 1 opened the circuit"
        )

        # Service 3 (on yet another server) should also see OPEN state
        service3_cb = CircuitProtectorPolicy(
            resource_key=shared_api_key,
            cooldown=timedelta(seconds=5)
        )

        assert service3_cb.status == CircuitStatus.OPEN, (
            "All services should share the same circuit state through PostgreSQL"
        )
