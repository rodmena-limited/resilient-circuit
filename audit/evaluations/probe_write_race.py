#!/usr/bin/env python3
"""Live multiprocess probe for the PostgresStorage cross-process write race (ticket #1).

Origin: bulkman audit report — load → decide → save is not atomic across processes;
a process holding a stale local CLOSED can clobber a stored OPEN (last-writer-wins),
silently erasing the protection signal. Two openers also race on open_until.

Scenarios:
  S1  stale-CLOSED clobber   — A trips OPEN; B (constructed earlier, local CLOSED)
                               records a success and blindly persists. Stored state
                               must remain OPEN, and B must reject its next call.
  S2  concurrent openers     — a later opener must not move the stored cooldown end
                               (first opener wins on open_until).
  S3  recovery direction     — after cooldown expiry the circuit must still be able
                               to go OPEN → HALF_OPEN → CLOSED (the guard must not
                               block legitimate recovery). Passes pre-fix too; it is
                               the "cap works in both directions" control.
  S4  atomic read-modify-write — two processes interleave update_state increments;
                               no lost updates. SKIPped if the API does not exist
                               (pre-fix baseline).

Expected pre-fix:  S1 FAIL, S2 FAIL, S3 PASS, S4 SKIP  → exit 1 (probe goes red)
Expected post-fix: all PASS                             → exit 0

Run: python3 audit/evaluations/probe_write_race.py
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

logging.disable(logging.CRITICAL)  # the breaker logs every call at WARNING


def make_storage(namespace):
    from resilient_circuit.storage import PostgresStorage

    return PostgresStorage(DSN, namespace=namespace)


def make_policy(namespace, key, cooldown_s=60.0):
    from resilient_circuit.circuit_breaker import CircuitProtectorPolicy

    return CircuitProtectorPolicy(
        resource_key=key,
        storage=make_storage(namespace),
        cooldown=timedelta(seconds=cooldown_s),
        failure_limit=Fraction(1, 1),  # buffer size 1: a single failure trips OPEN
    )


def trip_open(policy):
    """Drive one failing protected call so the breaker opens.

    Since the distributed-admission fix (ticket #2), a breaker that refreshes
    into a peer's live OPEN rejects the call at admission instead of executing
    it — that is also a valid way for this circuit to end up OPEN locally.
    """
    from resilient_circuit.exceptions import ProtectedCallError

    @policy
    def failing():
        raise ValueError("dependency down")

    try:
        failing()
    except (ValueError, ProtectedCallError):
        pass


def succeed_once(policy):
    from resilient_circuit.exceptions import ProtectedCallError

    @policy
    def ok():
        return "ok"

    try:
        ok()
        return "admitted"
    except ProtectedCallError:
        return "rejected"


# ---------------------------------------------------------------- S1 children


def s1_child_b(ns, key, b_constructed, a_done, out):
    logging.disable(logging.CRITICAL)
    policy = make_policy(ns, key)  # no stored row yet -> local CLOSED
    b_constructed.set()
    a_done.wait(timeout=30)
    first = succeed_once(policy)  # stale local CLOSED -> blind persist (the clobber)
    second = succeed_once(policy)  # post-fix: must be rejected (adopted stored OPEN)
    out.put(("b", first, second))


def s1_child_a(ns, key, b_constructed, a_done, out):
    logging.disable(logging.CRITICAL)
    b_constructed.wait(timeout=30)
    policy = make_policy(ns, key)
    trip_open(policy)  # persists OPEN, open_until = now + 60s
    out.put(
        ("a", policy.status.value, getattr(policy._status, "open_until_timestamp", 0))
    )
    a_done.set()


# ---------------------------------------------------------------- S2 children


def s2_child(ns, key, delay_s, out, tag):
    logging.disable(logging.CRITICAL)
    policy = make_policy(ns, key)
    time.sleep(delay_s)
    intended = time.time() + 60.0  # the open_until this child is about to write
    trip_open(policy)
    # post-fix, a refused opener adopts the stored open_until, so the local
    # value after the trip shows adoption rather than the attempted write
    out.put((tag, intended, getattr(policy._status, "open_until_timestamp", 0)))


# ---------------------------------------------------------------- S4 children


def s4_child(ns, key, rounds, out):
    logging.disable(logging.CRITICAL)
    storage = make_storage(ns)
    applied = 0
    for _ in range(rounds):

        def bump(current):
            cur = current or {"state": "CLOSED", "failure_count": 0, "open_until": 0}
            return {
                "state": cur["state"],
                "failure_count": cur["failure_count"] + 1,
                "open_until": cur["open_until"],
            }

        storage.update_state(key, bump)
        applied += 1
    out.put(applied)


def run_scenarios():
    results = {}
    run_id = uuid.uuid4().hex[:8]

    # --- S1: stale-CLOSED clobber ------------------------------------------
    ns = f"probe-s1-{run_id}"
    key = "shared-dep"
    parent_storage = make_storage(ns)  # also serializes DDL before children start
    q = mp.Queue()
    b_constructed, a_done = mp.Event(), mp.Event()
    pb = mp.Process(target=s1_child_b, args=(ns, key, b_constructed, a_done, q))
    pa = mp.Process(target=s1_child_a, args=(ns, key, b_constructed, a_done, q))
    pb.start()
    pa.start()
    pb.join(60)
    pa.join(60)
    msgs = {}
    while not q.empty():
        m = q.get()
        msgs[m[0]] = m[1:]
    stored = parent_storage.get_state(key)
    stored_state = stored["state"] if stored else None
    b_first, b_second = msgs.get("b", (None, None))
    s1_ok = stored_state == "OPEN" and b_second == "rejected"
    results["S1 stale-CLOSED clobber"] = (
        s1_ok,
        f"A tripped {msgs.get('a', ('?',))[0]}; stored ended {stored_state} "
        f"(must be OPEN); B first call {b_first}, B second call {b_second} "
        f"(must be rejected)",
    )

    # --- S2: concurrent openers must not move the cooldown end -------------
    ns = f"probe-s2-{run_id}"
    key = "shared-dep"
    parent_storage = make_storage(ns)
    q = mp.Queue()
    p1 = mp.Process(target=s2_child, args=(ns, key, 0.0, q, "first"))
    p2 = mp.Process(target=s2_child, args=(ns, key, 3.0, q, "second"))
    p1.start()
    p2.start()
    p1.join(60)
    p2.join(60)
    opens = {}
    while not q.empty():
        tag, intended, local_after = q.get()
        opens[tag] = (intended, local_after)
    stored = parent_storage.get_state(key)
    stored_ou = stored["open_until"] if stored else 0
    first_intended = opens.get("first", (-99, -99))[0]
    second_intended, second_local = opens.get("second", (-99, -99))
    # storage truncates to whole seconds; the two attempts are ~3s apart
    s2_ok = (
        stored is not None
        and stored["state"] == "OPEN"
        and abs(stored_ou - first_intended) <= 1.5
        and abs(stored_ou - second_intended) > 1.5
        and abs(second_local - stored_ou) <= 1.5  # later opener adopted stored value
    )
    results["S2 first-opener-wins on open_until"] = (
        s2_ok,
        f"first intended open_until={first_intended:.0f}, second intended "
        f"{second_intended:.0f}, stored={stored_ou:.0f} (must equal first's); "
        f"second's local after trip {second_local:.0f} (must equal stored)",
    )

    # --- S3: recovery still works after expiry (both-directions control) ---
    ns = f"probe-s3-{run_id}"
    key = "shared-dep"
    parent_storage = make_storage(ns)
    policy = make_policy(ns, key, cooldown_s=2.0)
    trip_open(policy)
    mid = parent_storage.get_state(key)
    time.sleep(3.0)  # past cooldown
    outcome = succeed_once(policy)  # OPEN -> HALF_OPEN -> CLOSED
    stored = parent_storage.get_state(key)
    s3_ok = (
        mid is not None
        and mid["state"] == "OPEN"
        and outcome == "admitted"
        and stored is not None
        and stored["state"] == "CLOSED"
    )
    results["S3 recovery after expiry (guard must not block)"] = (
        s3_ok,
        f"after trip stored={mid['state'] if mid else None}, probe call {outcome}, "
        f"after recovery stored={stored['state'] if stored else None} (must be CLOSED)",
    )

    # --- S4: atomic read-modify-write, no lost updates ---------------------
    ns = f"probe-s4-{run_id}"
    key = "counter"
    parent_storage = make_storage(ns)
    if not hasattr(parent_storage, "update_state"):
        results["S4 update_state lost-update check"] = (
            None,
            "SKIP: storage has no update_state API (pre-fix baseline)",
        )
    else:
        rounds = 25
        q = mp.Queue()
        procs = [
            mp.Process(target=s4_child, args=(ns, key, rounds, q)) for _ in range(2)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(120)
        total_applied = 0
        while not q.empty():
            total_applied += q.get()
        stored = parent_storage.get_state(key)
        count = stored["failure_count"] if stored else 0
        s4_ok = total_applied == 2 * rounds and count == 2 * rounds
        results["S4 update_state lost-update check"] = (
            s4_ok,
            f"{total_applied} increments applied across 2 processes, stored "
            f"failure_count={count} (must be {2 * rounds})",
        )

    return results


def main():
    print(f"probe_write_race: DSN={DSN!r}")
    try:
        import psycopg  # noqa: F401
    except ImportError:
        print("ABORT: psycopg not installed")
        return 2
    try:
        results = run_scenarios()
    except Exception as e:
        print(f"ABORT: probe crashed: {type(e).__name__}: {e}")
        raise

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
