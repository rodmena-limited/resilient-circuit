"""Tests for CircuitProtectorPolicy thread-safety (ticket #5).

A shared policy must serialize status decisions, transitions and saves on a
per-policy lock so concurrent threads cannot corrupt the shared status
objects; the lock must never be held across the protected callable; and a
stale in-flight success must never shortcut the OPEN cooldown. The live
probe is audit/evaluations/probe_policy_thread_safety.py.
"""

import threading
import time
from datetime import timedelta
from fractions import Fraction

import pytest

from resilient_circuit.circuit_breaker import (
    CircuitProtectorPolicy,
    CircuitStatus,
    StatusClosed,
    StatusOpen,
)
from resilient_circuit.exceptions import ProtectedCallError
from resilient_circuit.storage import InMemoryStorage


def make_policy(storage, key="race-dep", cooldown=timedelta(seconds=60), **kwargs):
    return CircuitProtectorPolicy(
        resource_key=key,
        storage=storage,
        cooldown=cooldown,
        failure_limit=Fraction(1, 1),
        **kwargs,
    )


def hammer(policy, seconds=0.6):
    """Run success threads and a failure thread against one policy."""
    stop = threading.Event()

    @policy
    def ok():
        return "ok"

    @policy
    def failing():
        raise ValueError("down")

    def loop(fn):
        while not stop.is_set():
            try:
                fn()
            except Exception:
                pass

    threads = [threading.Thread(target=loop, args=(ok,)) for _ in range(3)]
    threads += [threading.Thread(target=loop, args=(failing,))]
    for t in threads:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in threads:
        t.join()


class TestConcurrentCalls:
    def test_no_spurious_open_to_half_open_transitions(self):
        """With a 60s cooldown and a short hammer, HALF_OPEN can only appear
        via the OPEN->HALF_OPEN race that the fix removes."""
        storage = InMemoryStorage()
        transitions = []
        policy = make_policy(
            storage,
            on_status_change=lambda pol, old, new: transitions.append((old, new)),
        )
        hammer(policy)
        spurious = [
            t for t in transitions if t == (CircuitStatus.OPEN, CircuitStatus.HALF_OPEN)
        ]
        assert not spurious
        assert all(a is not b for a, b in transitions)  # no old==new callbacks

    def test_stored_state_valid_and_consistent_after_hammer(self):
        storage = InMemoryStorage()
        policy = make_policy(storage)
        hammer(policy)
        stored = storage.get_state("race-dep")
        assert stored is not None
        assert stored["state"] in ("CLOSED", "OPEN", "HALF_OPEN")
        assert isinstance(stored["failure_count"], int)
        assert isinstance(stored["open_until"], float)

    def test_stored_open_is_honored_after_hammer(self):
        """Whatever the interleaving, a stored OPEN still rejects with zero
        executions on the next admission."""
        storage = InMemoryStorage()
        policy = make_policy(storage)
        hammer(policy)
        stored = storage.get_state("race-dep")
        if stored is not None and stored["state"] == "OPEN":
            executions = []

            @policy
            def guarded():
                executions.append(1)

            with pytest.raises(ProtectedCallError):
                guarded()
            assert executions == []


class TestStaleSuccessCannotShortcutCooldown:
    def test_status_open_mark_success_is_noop(self):
        """A success while OPEN is a stale in-flight call, not a recovery
        probe: it must not transition to HALF_OPEN."""
        policy = make_policy(InMemoryStorage())
        status = StatusOpen(
            policy=policy,
            previous_status=StatusClosed(policy=policy),
            open_until=time.time() + 3600,
        )
        status.mark_success()
        assert status.status_type is CircuitStatus.OPEN

    def test_reentrant_callback_does_not_deadlock(self):
        """on_status_change may re-enter the policy (RLock); the decorated
        call inside a callback must not deadlock."""
        storage = InMemoryStorage()
        policy = make_policy(storage)

        @policy
        def ok():
            return "ok"

        def on_change(policy, old, new):
            assert ok() == "ok"  # re-enter the policy from the callback

        policy._on_status_change = on_change
        assert ok() == "ok"
