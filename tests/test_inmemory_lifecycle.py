"""Tests for InMemoryStorage lifecycle resiliency (ticket #3) and backend
observability (ticket #6).

InMemoryStorage must not grow without bound: a configurable entry cap with
least-recently-used eviction, where a live OPEN (unexpired protection signal)
is never evicted. All backends gain delete_state() and a backend_name.
"""

import time

import pytest

from resilient_circuit.storage import (
    CircuitBreakerStorage,
    InMemoryStorage,
    PostgresStorage,
)

LIVE = time.time() + 3600
EXPIRED = time.time() - 10


class TestInMemoryEntryCap:
    def test_default_cap_is_applied(self):
        storage = InMemoryStorage()
        for i in range(InMemoryStorage().max_entries + 100):
            storage.set_state(f"k-{i}", "CLOSED", 0, 0)
        assert len(storage._states) <= InMemoryStorage().max_entries

    def test_cap_evicts_oldest_non_live_entry(self):
        storage = InMemoryStorage(max_entries=3)
        storage.set_state("a", "CLOSED", 0, 0)
        storage.set_state("b", "CLOSED", 0, 0)
        storage.set_state("c", "CLOSED", 0, 0)
        storage.set_state("d", "CLOSED", 0, 0)
        assert "a" not in storage._states  # oldest evicted
        assert set(storage._states.keys()) == {"b", "c", "d"}

    def test_get_touches_recently_used_order(self):
        storage = InMemoryStorage(max_entries=3)
        storage.set_state("a", "CLOSED", 0, 0)
        storage.set_state("b", "CLOSED", 0, 0)
        storage.set_state("c", "CLOSED", 0, 0)
        storage.get_state("a")  # a is now most recently used
        storage.set_state("d", "CLOSED", 0, 0)
        assert "a" in storage._states  # touched, so not evicted
        assert "b" not in storage._states  # oldest non-live evicted

    def test_live_open_is_never_evicted_past_cap(self):
        storage = InMemoryStorage(max_entries=2)
        storage.set_state("a", "OPEN", 1, LIVE)
        storage.set_state("b", "OPEN", 1, LIVE)
        storage.set_state("c", "CLOSED", 0, 0)
        # both live OPENs survive even though the cap (2) is exceeded
        assert "a" in storage._states and "b" in storage._states
        assert storage.get_state("a")["state"] == "OPEN"
        assert storage.get_state("b")["state"] == "OPEN"

    def test_expired_open_is_evictable(self):
        storage = InMemoryStorage(max_entries=1)
        storage.set_state("old", "OPEN", 1, EXPIRED)
        storage.set_state("new", "CLOSED", 0, 0)
        assert "old" not in storage._states
        assert "new" in storage._states

    def test_max_entries_must_be_positive(self):
        with pytest.raises(ValueError):
            InMemoryStorage(max_entries=0)
        with pytest.raises(ValueError):
            InMemoryStorage(max_entries=-1)

    def test_unbounded_when_none(self):
        storage = InMemoryStorage(max_entries=None)
        for i in range(100):
            storage.set_state(f"k-{i}", "CLOSED", 0, 0)
        assert len(storage._states) == 100

    def test_guard_still_refuses_stale_write_after_eviction_churn(self):
        storage = InMemoryStorage(max_entries=4)
        storage.set_state("open-key", "OPEN", 3, LIVE)
        for i in range(10):
            storage.set_state(f"churn-{i}", "CLOSED", 0, 0)
        assert storage.get_state("open-key")["state"] == "OPEN"
        assert storage.set_state("open-key", "CLOSED", 0, 0) is False


class TestDeleteState:
    def test_delete_state_removes_and_reports(self):
        storage = InMemoryStorage()
        storage.set_state("key", "OPEN", 5, LIVE)
        assert storage.delete_state("key") is True
        assert storage.get_state("key") is None
        assert storage.delete_state("key") is False

    def test_delete_state_missing_returns_false(self):
        storage = InMemoryStorage()
        assert storage.delete_state("never-existed") is False

    def test_delete_state_releases_guard(self):
        storage = InMemoryStorage()
        storage.set_state("key", "OPEN", 5, LIVE)
        assert storage.set_state("key", "CLOSED", 0, 0) is False
        storage.delete_state("key")
        assert storage.set_state("key", "CLOSED", 0, 0) is True

    def test_base_class_delete_state_is_safe_noop(self):
        class Dummy(CircuitBreakerStorage):
            def get_state(self, resource_key):
                return None

            def set_state(self, *args, **kwargs):
                return True

        assert Dummy().delete_state("key") is False


class TestBackendIdentity:
    def test_backend_name_attributes(self):
        assert InMemoryStorage().backend_name == "in-memory"
        assert CircuitBreakerStorage.backend_name == "unknown"

    def test_postgres_backend_name(self):
        assert PostgresStorage.backend_name == "postgres"
