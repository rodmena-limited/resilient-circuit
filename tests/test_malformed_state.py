"""Tests for malformed stored state resilience (ticket #4).

A corrupt stored state (unknown state value, non-numeric failure_count or
open_until) must never crash the protected call: the policy logs it, ignores
it, falls back to CLOSED, and self-heals the row on the next successful
write. This is backend-agnostic (reproduced against both backends); the live
probe is audit/evaluations/probe_malformed_state.py.
"""

import os
import uuid
from datetime import timedelta

import pytest

from resilient_circuit.circuit_breaker import CircuitProtectorPolicy, CircuitStatus
from resilient_circuit.storage import InMemoryStorage, PostgresStorage


def corrupt_and_guard(
    storage, key, state="SOMETHING_ELSE", failure_count=0, open_until=None
):
    """Plant a corrupt row and run one guarded call through it."""
    storage._states[key] = {
        "state": state,
        "failure_count": failure_count,
        "open_until": open_until,
    }
    policy = CircuitProtectorPolicy(
        resource_key=key, storage=storage, cooldown=timedelta(seconds=1)
    )

    @policy
    def ok():
        return "ok"

    return ok()


class TestMalformedStateNeverCrashes:
    def test_invalid_state_string_survives(self):
        assert (
            corrupt_and_guard(InMemoryStorage(), "k1", state="SOMETHING_ELSE") == "ok"
        )

    def test_garbage_open_until_survives(self):
        assert (
            corrupt_and_guard(
                InMemoryStorage(), "k2", state="OPEN", open_until="not-a-number"
            )
            == "ok"
        )

    def test_garbage_failure_count_survives(self):
        assert corrupt_and_guard(InMemoryStorage(), "k3", failure_count="lots") == "ok"

    def test_missing_state_key_survives(self):
        storage = InMemoryStorage()
        storage._states["k4"] = {"failure_count": 0, "open_until": 0}
        policy = CircuitProtectorPolicy(
            resource_key="k4", storage=storage, cooldown=timedelta(seconds=1)
        )

        @policy
        def ok():
            return "ok"

        assert ok() == "ok"

    def test_malformed_state_falls_back_to_closed(self):
        storage = InMemoryStorage()
        storage._states["k5"] = {
            "state": "SOMETHING_ELSE",
            "failure_count": 0,
            "open_until": 0,
        }
        policy = CircuitProtectorPolicy(
            resource_key="k5", storage=storage, cooldown=timedelta(seconds=1)
        )
        assert policy.status == CircuitStatus.CLOSED

    def test_malformed_state_self_heals_on_next_write(self):
        storage = InMemoryStorage()
        storage._states["k6"] = {
            "state": "SOMETHING_ELSE",
            "failure_count": 0,
            "open_until": 0,
        }
        policy = CircuitProtectorPolicy(
            resource_key="k6", storage=storage, cooldown=timedelta(seconds=1)
        )

        @policy
        def ok():
            return "ok"

        assert ok() == "ok"
        stored = storage.get_state("k6")
        assert stored is not None
        assert stored["state"] in ("CLOSED", "OPEN", "HALF_OPEN")

    def test_malformed_refresh_keeps_local_status(self):
        """The refresh path must not crash and must keep the local view."""
        storage = InMemoryStorage()
        policy = CircuitProtectorPolicy(
            resource_key="k7", storage=storage, cooldown=timedelta(seconds=1)
        )

        @policy
        def ok():
            return "ok"

        assert ok() == "ok"  # healthy first call
        # storage now starts returning a corrupt row on refresh
        storage._states["k7"] = {
            "state": "GARBAGE",
            "failure_count": 0,
            "open_until": 0,
        }
        assert ok() == "ok"  # refresh ignores corrupt row, local CLOSED admits
        assert policy.status == CircuitStatus.CLOSED

    def test_valid_stored_state_still_applied(self):
        """Regression guard: well-formed stored state is honored, not reset."""
        storage = InMemoryStorage()
        storage.set_state("k8", "OPEN", 3, 0)  # OPEN with expired cooldown
        policy = CircuitProtectorPolicy(
            resource_key="k8", storage=storage, cooldown=timedelta(seconds=1)
        )
        assert policy.status == CircuitStatus.OPEN


@pytest.fixture
def pg_storage():
    """PostgresStorage with a unique namespace; skip if PG is down."""
    db_host = os.getenv("RC_DB_HOST")
    db_password = os.getenv("RC_DB_PASSWORD")
    if not (db_host and db_password):
        pytest.skip("PostgreSQL not configured")
    connection_string = (
        f"host={db_host} port={os.getenv('RC_DB_PORT', '5432')} "
        f"dbname={os.getenv('RC_DB_NAME', 'resilient_circuit_db')} "
        f"user={os.getenv('RC_DB_USER', 'postgres')} password={db_password}"
    )
    namespace = f"test-malformed-{uuid.uuid4().hex[:8]}"
    try:
        storage = PostgresStorage(connection_string, namespace=namespace)
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    yield storage
    with storage._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM rc_circuit_breakers WHERE namespace = %s", (namespace,)
            )
            conn.commit()


class TestMalformedStatePostgres:
    def test_corrupt_pg_row_does_not_crash_and_self_heals(self, pg_storage):
        key = "corrupt-row"
        with pg_storage._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO rc_circuit_breakers "
                    "(resource_key, namespace, state, failure_count, open_until) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (key, pg_storage.namespace, "SOMETHING_ELSE", 0, None),
                )
                conn.commit()
        policy = CircuitProtectorPolicy(
            resource_key=key, storage=pg_storage, cooldown=timedelta(seconds=1)
        )

        @policy
        def ok():
            return "ok"

        assert ok() == "ok"  # no crash
        stored = pg_storage.get_state(key)
        assert stored is not None
        assert stored["state"] in ("CLOSED", "OPEN", "HALF_OPEN")  # self-healed
