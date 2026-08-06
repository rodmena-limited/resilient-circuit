"""Tests for distributed admission (ticket #2).

A process must honor a peer's stored OPEN *before* executing the protected
callable — not one-call-later via the refused-write adoption from ticket #1.
The live multiprocess reproduction is audit/evaluations/
probe_distributed_admission.py; these tests pin the semantics in-process.
"""

import time
from datetime import timedelta
from fractions import Fraction
from unittest.mock import Mock

import pytest

from resilient_circuit.circuit_breaker import CircuitProtectorPolicy, CircuitStatus
from resilient_circuit.exceptions import ProtectedCallError
from resilient_circuit.storage import InMemoryStorage


def make_policy(storage, key="shared-dep", cooldown=timedelta(seconds=60), **kwargs):
    return CircuitProtectorPolicy(
        resource_key=key,
        storage=storage,
        cooldown=cooldown,
        failure_limit=Fraction(1, 1),
        **kwargs,
    )


def trip_open(policy):
    @policy
    def failing():
        raise ValueError("dependency down")

    with pytest.raises(ValueError):
        failing()


class TestAdmissionHonorsPeerOpen:
    def test_peer_open_rejects_call_without_executing_it(self):
        storage = InMemoryStorage()
        policy_b = make_policy(storage)  # constructed first; never writes
        policy_a = make_policy(storage)
        trip_open(policy_a)

        executions = []

        @policy_b
        def guarded():
            executions.append(1)

        with pytest.raises(ProtectedCallError):
            guarded()
        assert executions == []  # zero executions, not one-then-adopt
        assert policy_b.status == CircuitStatus.OPEN

    def test_adoption_fires_on_status_change_callback(self):
        storage = InMemoryStorage()
        callback = Mock()
        policy_b = make_policy(storage, on_status_change=callback)
        policy_a = make_policy(storage)
        trip_open(policy_a)

        @policy_b
        def guarded():
            pass

        with pytest.raises(ProtectedCallError):
            guarded()
        callback.assert_called_once_with(
            policy_b, CircuitStatus.CLOSED, CircuitStatus.OPEN
        )

    def test_adopted_open_recovers_after_cooldown_via_refresh_path(self):
        """Both directions: honoring a peer's OPEN must not wedge the circuit."""
        storage = InMemoryStorage()
        policy_b = make_policy(storage, cooldown=timedelta(milliseconds=100))
        policy_a = make_policy(storage, cooldown=timedelta(milliseconds=100))
        trip_open(policy_a)

        @policy_b
        def guarded():
            return "ok"

        with pytest.raises(ProtectedCallError):
            guarded()
        time.sleep(0.15)  # past cooldown
        assert guarded() == "ok"  # OPEN -> HALF_OPEN -> CLOSED
        assert policy_b.status == CircuitStatus.CLOSED
        assert storage.get_state("shared-dep")["state"] == "CLOSED"


class TestRefreshThrottling:
    def test_interval_uses_local_view_between_refreshes(self):
        storage = InMemoryStorage()
        policy_b = make_policy(
            storage, admission_refresh_interval=timedelta(milliseconds=200)
        )

        @policy_b
        def guarded():
            return "ok"

        assert guarded() == "ok"  # starts the interval window
        policy_a = make_policy(storage)
        trip_open(policy_a)
        # inside the interval: local view (CLOSED) still admits
        assert guarded() == "ok"
        time.sleep(0.25)  # interval elapses
        with pytest.raises(ProtectedCallError):
            guarded()

    def test_no_interval_refreshes_every_call(self):
        storage = InMemoryStorage()
        policy_b = make_policy(storage)

        @policy_b
        def guarded():
            return "ok"

        assert guarded() == "ok"
        policy_a = make_policy(storage)
        trip_open(policy_a)
        with pytest.raises(ProtectedCallError):
            guarded()  # very next call already honors the peer's OPEN


class TestRefreshFailureIsFailOpen:
    def test_storage_read_failure_keeps_local_view(self):
        storage = InMemoryStorage()
        policy = make_policy(storage)

        @policy
        def guarded():
            return "ok"

        assert guarded() == "ok"
        # storage starts failing reads; local view is CLOSED -> still admits
        policy.storage = Mock()
        policy.storage.get_state.side_effect = RuntimeError("db down")
        policy.storage.set_state.return_value = True
        assert guarded() == "ok"

    def test_storage_read_failure_keeps_adopted_open(self):
        """Fail-open means keep the LOCAL view — an adopted OPEN stays OPEN."""
        storage = InMemoryStorage()
        policy_b = make_policy(storage)
        policy_a = make_policy(storage)
        trip_open(policy_a)

        @policy_b
        def guarded():
            return "ok"

        with pytest.raises(ProtectedCallError):
            guarded()  # adopts the peer's OPEN
        policy_b.storage = Mock()
        policy_b.storage.get_state.side_effect = RuntimeError("db down")
        with pytest.raises(ProtectedCallError):
            guarded()  # still OPEN from the local (adopted) view
