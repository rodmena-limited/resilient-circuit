#!/usr/bin/env python3
"""Live multiprocess probe for distributed admission (ticket #2).

Ticket #1 made persistence safe: a stale writer cannot clobber a live OPEN, and a
refused writer adopts the stored state. But admission was still local: a process
that never writes never learns of a peer's OPEN, and a stale process still executes
its protected callable once before its refused write triggers adoption. Both mean
the failing dependency gets hit after the circuit is already OPEN in storage.

Scenarios:
  D1  zero-execution admission — A trips OPEN; B (constructed earlier, never wrote,
                                 local CLOSED) attempts a call. B's callable must
                                 run ZERO times and the call must be rejected.
  D2  refresh throttling       — with admission_refresh_interval set, B admits from
                                 its local view inside the interval window (no
                                 storage read storm), then rejects after the
                                 interval elapses. Skipped if the parameter does
                                 not exist (pre-fix baseline).
  D3  adopted OPEN recovers    — B adopts a peer's OPEN with a short cooldown; after
                                 expiry B's call is admitted and closes the circuit
                                 (both-directions control).

Expected pre-fix (25cb4a3):  D1 FAIL, D2 SKIP, D3 PASS  → exit 1 (red)
Expected post-fix:           all PASS                    → exit 0

Run: python3 audit/evaluations/probe_distributed_admission.py
Env: RC_PROBE_DSN (default "dbname=resilient_circuit_test", local socket peer auth)
"""

import logging
import multiprocessing as mp
import os
import sys
import time
import uuid
from datetime import timedelta
from fractions import Fraction

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

DSN = os.environ.get("RC_PROBE_DSN", "dbname=resilient_circuit_test")

logging.disable(logging.CRITICAL)


def make_storage(namespace):
    from resilient_circuit.storage import PostgresStorage

    return PostgresStorage(DSN, namespace=namespace)


def make_policy(namespace, key, cooldown_s=60.0, **kwargs):
    from resilient_circuit.circuit_breaker import CircuitProtectorPolicy

    return CircuitProtectorPolicy(
        resource_key=key,
        storage=make_storage(namespace),
        cooldown=timedelta(seconds=cooldown_s),
        failure_limit=Fraction(1, 1),
        **kwargs,
    )


def trip_open(policy):
    @policy
    def failing():
        raise ValueError("dependency down")

    try:
        failing()
    except ValueError:
        pass


def attempt(policy, counter):
    """One protected call; returns 'admitted' or 'rejected', counting executions."""
    from resilient_circuit.exceptions import ProtectedCallError

    @policy
    def guarded():
        counter[0] += 1
        return "ok"

    try:
        guarded()
        return "admitted"
    except ProtectedCallError:
        return "rejected"


# ---------------------------------------------------------------- D1 children


def d1_child_b(ns, key, b_ready, a_done, out):
    logging.disable(logging.CRITICAL)
    policy = make_policy(ns, key)  # constructed before A trips; never writes
    b_ready.set()
    a_done.wait(timeout=30)
    executions = [0]
    outcome = attempt(policy, executions)
    out.put(("b", outcome, executions[0], policy.status.value))


def d1_child_a(ns, key, b_ready, a_done, out):
    logging.disable(logging.CRITICAL)
    b_ready.wait(timeout=30)
    policy = make_policy(ns, key)
    trip_open(policy)
    out.put(("a", policy.status.value))
    a_done.set()


def run_scenarios():
    results = {}
    run_id = uuid.uuid4().hex[:8]

    # --- D1: peer's OPEN must be honored with zero executions --------------
    ns = f"probe-d1-{run_id}"
    key = "shared-dep"
    parent_storage = make_storage(ns)  # serialize DDL before children start
    q = mp.Queue()
    b_ready, a_done = mp.Event(), mp.Event()
    pb = mp.Process(target=d1_child_b, args=(ns, key, b_ready, a_done, q))
    pa = mp.Process(target=d1_child_a, args=(ns, key, b_ready, a_done, q))
    pb.start()
    pa.start()
    pb.join(60)
    pa.join(60)
    msgs = {}
    while not q.empty():
        m = q.get()
        msgs[m[0]] = m[1:]
    outcome, executions, b_status = msgs.get("b", (None, -1, None))
    stored = parent_storage.get_state(key)
    d1_ok = (
        outcome == "rejected"
        and executions == 0
        and stored is not None
        and stored["state"] == "OPEN"
    )
    results["D1 zero-execution admission against peer OPEN"] = (
        d1_ok,
        f"A tripped {msgs.get('a', ('?',))[0]}; B's call {outcome} with "
        f"{executions} execution(s) (must be rejected with 0), B ended {b_status}, "
        f"stored {stored['state'] if stored else None}",
    )

    # --- D2: admission_refresh_interval throttles the storage read ---------
    ns = f"probe-d2-{run_id}"
    key = "shared-dep"
    try:
        policy_b = make_policy(ns, key, admission_refresh_interval=timedelta(seconds=2))
    except TypeError:
        results["D2 refresh interval throttling"] = (
            None,
            "SKIP: admission_refresh_interval not supported (pre-fix baseline)",
        )
        policy_b = None
    if policy_b is not None:
        executions = [0]
        # first call: fresh policy, interval starts; circuit CLOSED everywhere
        first = attempt(policy_b, executions)
        # peer trips OPEN out-of-band
        policy_a = make_policy(ns, key)
        trip_open(policy_a)
        # inside the interval: B still admits from its local view
        inside = attempt(policy_b, executions)
        time.sleep(2.2)  # let the interval elapse
        after = attempt(policy_b, executions)
        d2_ok = first == "admitted" and inside == "admitted" and after == "rejected"
        results["D2 refresh interval throttling"] = (
            d2_ok,
            f"first={first} (admitted), inside-interval={inside} (admitted: local "
            f"view, throttled), after-interval={after} (must be rejected)",
        )

    # --- D3: adopted OPEN still recovers after cooldown --------------------
    ns = f"probe-d3-{run_id}"
    key = "shared-dep"
    parent_storage = make_storage(ns)
    policy_b = make_policy(ns, key, cooldown_s=2.0)
    policy_a = make_policy(ns, key, cooldown_s=2.0)
    trip_open(policy_a)
    executions = [0]
    during = attempt(policy_b, executions)  # rejected (post-fix) or admitted (pre)
    time.sleep(3.0)  # past cooldown
    after = attempt(policy_b, executions)
    stored = parent_storage.get_state(key)
    d3_ok = after == "admitted" and stored is not None and stored["state"] == "CLOSED"
    results["D3 adopted OPEN recovers after expiry"] = (
        d3_ok,
        f"during cooldown B {during}; after expiry B {after} (must be admitted), "
        f"stored ended {stored['state'] if stored else None} (must be CLOSED)",
    )

    return results


def main():
    print(f"probe_distributed_admission: DSN={DSN!r}")
    try:
        import psycopg  # noqa: F401
    except ImportError:
        print("ABORT: psycopg not installed")
        return 2
    results = run_scenarios()
    failed = False
    for name, (ok, detail) in results.items():
        tag = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        if ok is False:
            failed = True
        print(f"  [{tag}] {name}\n         {detail}")
    print("probe result:", "RED (defect present)" if failed else "GREEN")
    return 1 if failed else 0


if __name__ == "__main__":
    mp.set_start_method("fork")
    sys.exit(main())
