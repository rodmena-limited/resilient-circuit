"""Tests for storage write-guard and atomic read-modify-write (ticket #1).

Covers the cross-process write race reported by the bulkman audit: the
load -> decide -> save cycle was last-writer-wins, so a process holding a
stale local CLOSED could clobber a stored OPEN and silently erase the
protection signal. The multiprocess live reproduction lives in
audit/evaluations/probe_write_race.py; these tests pin the semantics
in-process (threads) for both backends.
"""

import os
import threading
import time
import uuid
from datetime import timedelta
from fractions import Fraction

import pytest

from resilient_circuit.circuit_breaker import CircuitProtectorPolicy, CircuitStatus
from resilient_circuit.exceptions import ProtectedCallError
from resilient_circuit.storage import InMemoryStorage, PostgresStorage

LIVE = time.time() + 3600  # an unexpired cooldown end
EXPIRED = time.time() - 10


@pytest.fixture
def pg_storage():
    """PostgresStorage with a unique namespace per test; skip if PG is down."""
    db_host = os.getenv("RC_DB_HOST")
    db_port = os.getenv("RC_DB_PORT", "5432")
    db_name = os.getenv("RC_DB_NAME", "resilient_circuit_db")
    db_user = os.getenv("RC_DB_USER", "postgres")
    db_password = os.getenv("RC_DB_PASSWORD")
    connection_string = (
        f"host={db_host} port={db_port} dbname={db_name} "
        f"user={db_user} password={db_password}"
    )
    namespace = f"test-atomicity-{uuid.uuid4().hex[:8]}"
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


class GuardContractMixin:
    """Guard semantics that must hold identically for every backend."""

    def test_blind_write_applies_when_no_state_exists(self, storage):
        assert storage.set_state("key", "CLOSED", 0, 0) is True
        assert storage.get_state("key")["state"] == "CLOSED"

    def test_stale_closed_cannot_clobber_live_open(self, storage):
        assert storage.set_state("key", "OPEN", 5, LIVE) is True
        assert storage.set_state("key", "CLOSED", 0, 0) is False
        stored = storage.get_state("key")
        assert stored["state"] == "OPEN"
        assert stored["failure_count"] == 5

    def test_stale_half_open_cannot_clobber_live_open(self, storage):
        assert storage.set_state("key", "OPEN", 5, LIVE) is True
        assert storage.set_state("key", "HALF_OPEN", 0, 0) is False
        assert storage.get_state("key")["state"] == "OPEN"

    def test_second_opener_cannot_move_cooldown_end(self, storage):
        assert storage.set_state("key", "OPEN", 5, LIVE) is True
        assert storage.set_state("key", "OPEN", 7, LIVE + 1800) is False
        stored = storage.get_state("key")
        assert stored["state"] == "OPEN"
        # first opener wins: cooldown end unchanged (storage keeps seconds)
        assert abs(stored["open_until"] - LIVE) <= 1.0

    def test_any_write_applies_once_cooldown_expired(self, storage):
        """The other direction: the guard must not block recovery."""
        assert storage.set_state("key", "OPEN", 5, EXPIRED) is True
        assert storage.set_state("key", "HALF_OPEN", 0, 0) is True
        assert storage.get_state("key")["state"] == "HALF_OPEN"
        assert storage.set_state("key", "CLOSED", 0, 0) is True
        assert storage.get_state("key")["state"] == "CLOSED"

    def test_update_state_creates_state_when_absent(self, storage):
        def init(current):
            assert current is None
            return {"state": "CLOSED", "failure_count": 0, "open_until": 0}

        result = storage.update_state("key", init)
        assert result["state"] == "CLOSED"
        assert storage.get_state("key")["state"] == "CLOSED"

    def test_update_state_mutator_none_leaves_state_unchanged(self, storage):
        storage.set_state("key", "OPEN", 3, LIVE)
        result = storage.update_state("key", lambda current: None)
        assert result["state"] == "OPEN"
        assert storage.get_state("key")["state"] == "OPEN"

    def test_update_state_can_deliberately_override_live_open(self, storage):
        """Administrative reset path: RMW writes are unguarded by design."""
        storage.set_state("key", "OPEN", 5, LIVE)
        storage.update_state(
            "key",
            lambda current: {"state": "CLOSED", "failure_count": 0, "open_until": 0},
        )
        assert storage.get_state("key")["state"] == "CLOSED"

    def test_update_state_concurrent_increments_lose_nothing(self, storage):
        threads_n, rounds = 4, 25

        def bump(current):
            cur = current or {"state": "CLOSED", "failure_count": 0, "open_until": 0}
            return {
                "state": cur["state"],
                "failure_count": cur["failure_count"] + 1,
                "open_until": cur["open_until"],
            }

        def worker():
            for _ in range(rounds):
                storage.update_state("key", bump)

        threads = [threading.Thread(target=worker) for _ in range(threads_n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert storage.get_state("key")["failure_count"] == threads_n * rounds


class TestInMemoryGuardContract(GuardContractMixin):
    @pytest.fixture
    def storage(self):
        return InMemoryStorage()

    def test_get_state_returns_copy_not_alias(self):
        storage = InMemoryStorage()
        storage.set_state("key", "OPEN", 5, LIVE, execution_log=[False, False])
        stored = storage.get_state("key")
        stored["state"] = "CLOSED"
        stored["execution_log"].append(True)
        fresh = storage.get_state("key")
        assert fresh["state"] == "OPEN"
        assert fresh["execution_log"] == [False, False]


class TestPostgresGuardContract(GuardContractMixin):
    @pytest.fixture
    def storage(self, pg_storage):
        return pg_storage


class TestBreakerAdoptsStoredProtectionSignal:
    """A breaker whose refused write reveals a live stored OPEN must adopt it.

    Since ticket #2 a breaker refreshes shared state before admission, so a
    stale process normally never gets to write at all. The refused-write
    adoption remains as defense-in-depth for the throttled-refresh window
    (admission_refresh_interval); these tests pin it down through exactly
    that window.
    """

    def _policy(self, storage, key="shared-dep", cooldown=timedelta(seconds=60)):
        return CircuitProtectorPolicy(
            resource_key=key,
            storage=storage,
            cooldown=cooldown,
            failure_limit=Fraction(1, 1),
            # a refresh window so large it never re-fires during the test:
            # admission uses B's stale local view, as pre-ticket-2 code did
            admission_refresh_interval=timedelta(hours=1),
        )

    def test_stale_success_does_not_clobber_open_and_process_adopts_it(self):
        storage = InMemoryStorage()
        policy_b = self._policy(storage)

        @policy_b
        def ok():
            return "ok"

        assert ok() == "ok"  # starts B's refresh window; persists CLOSED

        # A trips the circuit OPEN out-of-band
        policy_a = CircuitProtectorPolicy(
            resource_key="shared-dep",
            storage=storage,
            cooldown=timedelta(seconds=60),
            failure_limit=Fraction(1, 1),
        )

        @policy_a
        def failing():
            raise ValueError("dependency down")

        with pytest.raises(ValueError):
            failing()
        assert policy_a.status == CircuitStatus.OPEN
        assert storage.get_state("shared-dep")["state"] == "OPEN"

        # B, inside its refresh window with a stale CLOSED view, records a
        # success and blindly persists
        assert ok() == "ok"  # admitted from B's throttled local view
        # ... but the stored protection signal survived the blind write
        assert storage.get_state("shared-dep")["state"] == "OPEN"
        # ... and B adopted it via the refused write: the next call is rejected
        assert policy_b.status == CircuitStatus.OPEN
        with pytest.raises(ProtectedCallError):
            ok()

    def test_adopted_open_still_recovers_after_cooldown(self):
        """Both directions: adoption must not wedge the circuit permanently."""
        storage = InMemoryStorage()
        cooldown = timedelta(milliseconds=100)
        policy_b = self._policy(storage, key="recover-dep", cooldown=cooldown)

        @policy_b
        def ok():
            return "ok"

        assert ok() == "ok"  # starts B's refresh window

        policy_a = CircuitProtectorPolicy(
            resource_key="recover-dep",
            storage=storage,
            cooldown=cooldown,
            failure_limit=Fraction(1, 1),
        )

        @policy_a
        def failing():
            raise ValueError("dependency down")

        with pytest.raises(ValueError):
            failing()

        ok()  # stale success -> refused write -> B adopts OPEN
        assert policy_b.status == CircuitStatus.OPEN
        time.sleep(0.15)  # past cooldown
        assert ok() == "ok"  # OPEN -> HALF_OPEN -> CLOSED
        assert policy_b.status == CircuitStatus.CLOSED
        assert storage.get_state("recover-dep")["state"] == "CLOSED"
