#!/usr/bin/env python3
"""Live probe for CircuitProtectorPolicy thread-safety (ticket #5).

Pre-fix (0.5.0): a shared policy mutated one status object from concurrent
threads — mark_success/mark_failure interleaved and self._status was swapped
mid-sequence. A success landing on a just-swapped OPEN object transitioned
OPEN -> HALF_OPEN, shortcutting the cooldown (spurious transition), and the
protected callable executed while storage already held OPEN.

Scenarios (one policy, 3 success threads + 1 failure thread, long cooldown):
  T1  no spurious OPEN->HALF_OPEN  — with a 60s cooldown and a short hammer,
      HALF_OPEN can only appear via the race; post-fix it never does.
  T2  stored state stays valid      — after the hammer the stored dict is a
      valid CircuitStatus (never garbage, never half-written).
  T3  no old==new callbacks         — on_status_change never fires with equal
      statuses.
  T4  admitted-OPEN is rejected     — a call after the hammer, when the
      stored circuit is OPEN, is rejected with zero executions.

Expected pre-fix:  T1 FAIL (spurious transitions) -> red (probabilistic but
reliable over a 2s hammer)
Expected post-fix: all PASS -> exit 0

Run: python3 audit/evaluations/probe_policy_thread_safety.py
"""

import logging
import os
import sys
import threading
import time
from datetime import timedelta
from fractions import Fraction

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

logging.disable(logging.CRITICAL)

HAMMER_SECONDS = 2.0
COOLDOWN_SECONDS = 60.0  # any OPEN -> HALF_OPEN during the hammer is spurious


def run_hammer(policy, seconds=HAMMER_SECONDS):
    """Drive success threads and failure threads against one policy.

    Returns the observed (old, new) transition list.
    """
    stop = threading.Event()
    transitions = []

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
    return transitions


def main():
    from resilient_circuit.circuit_breaker import (
        CircuitProtectorPolicy,
        CircuitStatus,
    )
    from resilient_circuit.exceptions import ProtectedCallError
    from resilient_circuit.storage import InMemoryStorage

    results = {}
    storage = InMemoryStorage()
    transitions = []
    policy = CircuitProtectorPolicy(
        resource_key="race-dep",
        storage=storage,
        cooldown=timedelta(seconds=COOLDOWN_SECONDS),
        failure_limit=Fraction(1, 1),
        on_status_change=lambda pol, old, new: transitions.append((old, new)),
    )
    run_hammer(policy)

    # --- T1: no spurious OPEN -> HALF_OPEN --------------------------------
    spurious = [
        t for t in transitions if t == (CircuitStatus.OPEN, CircuitStatus.HALF_OPEN)
    ]
    results["T1 no spurious OPEN->HALF_OPEN (cooldown shortcut)"] = (
        not spurious,
        f"{len(spurious)} spurious transition(s); observed "
        f"{[(a.value, b.value) for a, b in transitions[:12]]}",
    )

    # --- T2: stored state is always valid ---------------------------------
    stored = storage.get_state("race-dep")
    stored_ok = (
        stored is not None
        and stored["state"] in ("CLOSED", "OPEN", "HALF_OPEN")
        and isinstance(stored["failure_count"], int)
        and isinstance(stored["open_until"], float)
    )
    results["T2 stored state valid after hammer"] = (
        stored_ok,
        f"stored = {stored}",
    )

    # --- T3: no old==new callbacks ----------------------------------------
    equal = [t for t in transitions if t[0] is t[1]]
    results["T3 no old==new on_status_change"] = (
        not equal,
        f"{len(equal)} old==new callback(s)",
    )

    # --- T4: a post-hammer call honors a stored OPEN ----------------------
    executions = [0]

    @policy
    def guarded():
        executions[0] += 1
        return "ok"

    if stored is not None and stored["state"] == "OPEN":
        try:
            guarded()
            outcome = "admitted"
        except ProtectedCallError:
            outcome = "rejected"
        results["T4 stored-OPEN honored on next call"] = (
            outcome == "rejected" and executions[0] == 0,
            f"call {outcome} with {executions[0]} execution(s) "
            f"(must be rejected with 0)",
        )
    else:
        results["T4 stored-OPEN honored on next call"] = (
            None,
            "SKIP: circuit not OPEN after hammer",
        )

    failed = False
    for name, (ok, detail) in results.items():
        tag = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        if ok is False:
            failed = True
        print(f"  [{tag}] {name}\n         {detail}")
    print("probe result:", "RED (defect present)" if failed else "GREEN")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
