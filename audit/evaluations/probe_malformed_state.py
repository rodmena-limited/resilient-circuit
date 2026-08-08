#!/usr/bin/env python3
"""Live probe for malformed stored state (ticket #4).

Pre-fix (0.5.0): a corrupt stored state (unknown state value, non-numeric
open_until/failure_count) raised ValueError inside the protected call —
`_refresh_before_admission` guarded get_state() but not _adopt_stored().
One bad row broke every protected call on that key, in every backend.

Scenarios (run against InMemoryStorage and, when RC_PROBE_DSN is reachable,
PostgresStorage):
  M1  invalid state string   — call survives, falls back to CLOSED.
  M2  garbage open_until     — call survives (in-memory only: PostgreSQL's
                               TIMESTAMP column type rejects garbage at the
                               DB, which is its own protection).
  M3  self-heal              — the next successful write overwrites the
                               corrupt row with a valid stored state.

Expected pre-fix:  M1 FAIL, M2 FAIL (ValueError escapes the call) -> red
Expected post-fix: all non-SKIP PASS -> exit 0

Run: python3 audit/evaluations/probe_malformed_state.py
Env: RC_PROBE_DSN (default "dbname=resilient_circuit_test", local socket peer
auth). PostgreSQL scenarios are skipped when the DSN is unreachable.
"""

import logging
import os
import sys
import uuid
from datetime import timedelta

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

DSN = os.environ.get("RC_PROBE_DSN", "dbname=resilient_circuit_test")

logging.disable(logging.CRITICAL)


def run_backend(tag, make_storage, corrupt, supports_garbage_open_until, cleanup=None):
    from resilient_circuit.circuit_breaker import CircuitProtectorPolicy

    results = {}

    def guarded(policy):
        @policy
        def ok():
            return "ok"

        return ok()

    # --- M1: invalid state string -----------------------------------------
    key = "corrupt-key-m1"
    storage = make_storage()
    corrupt(storage, key, "SOMETHING_ELSE", 0, None)
    policy = CircuitProtectorPolicy(
        resource_key=key, storage=storage, cooldown=timedelta(seconds=1)
    )
    try:
        outcome = guarded(policy)
        ok = outcome == "ok"
    except Exception as e:
        outcome = f"CRASHED {type(e).__name__}: {e}"
        ok = False
    stored = storage.get_state(key)
    results[f"M1 {tag} invalid state string"] = (
        ok,
        f"guarded call -> {outcome!r} (must be 'ok'); stored after = {stored}",
    )

    # --- M2: garbage open_until -------------------------------------------
    if supports_garbage_open_until:
        key = "corrupt-key-m2"
        storage = make_storage()
        corrupt(storage, key, "OPEN", 0, "not-a-number")
        policy = CircuitProtectorPolicy(
            resource_key=key, storage=storage, cooldown=timedelta(seconds=1)
        )
        try:
            outcome = guarded(policy)
            ok = outcome == "ok"
        except Exception as e:
            outcome = f"CRASHED {type(e).__name__}: {e}"
            ok = False
        results[f"M2 {tag} garbage open_until"] = (
            ok,
            f"guarded call -> {outcome!r} (must be 'ok')",
        )
    else:
        results[f"M2 {tag} garbage open_until"] = (
            None,
            "SKIP: PostgreSQL TIMESTAMP column rejects garbage at the DB "
            "(column type is the protection)",
        )

    # --- M3: self-heal on next write --------------------------------------
    key = "corrupt-key-m3"
    storage = make_storage()
    corrupt(storage, key, "SOMETHING_ELSE", 0, None)
    policy = CircuitProtectorPolicy(
        resource_key=key, storage=storage, cooldown=timedelta(seconds=1)
    )
    try:
        guarded(policy)
    except Exception:
        pass
    healed = storage.get_state(key)
    healed_ok = healed is not None and healed["state"] in (
        "CLOSED",
        "OPEN",
        "HALF_OPEN",
    )
    results[f"M3 {tag} self-heal overwrites corrupt row"] = (
        healed_ok,
        f"stored after a successful call = {healed} (must be a valid state)",
    )

    if cleanup:
        cleanup(storage)
    return results


def run_inmemory():
    from resilient_circuit.storage import InMemoryStorage

    def corrupt(storage, key, state, failure_count, open_until):
        storage._states[key] = {
            "state": state,
            "failure_count": failure_count,
            "open_until": open_until,
        }

    return run_backend(
        "in-memory",
        lambda: InMemoryStorage(),
        corrupt,
        supports_garbage_open_until=True,
    )


def run_postgres():
    from resilient_circuit.storage import PostgresStorage

    namespace = f"probe-malformed-{uuid.uuid4().hex[:8]}"

    def make():
        return PostgresStorage(DSN, namespace=namespace)

    def corrupt(storage, key, state, failure_count, open_until):
        with storage._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO rc_circuit_breakers "
                    "(resource_key, namespace, state, failure_count, open_until) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (key, namespace, state, failure_count, open_until),
                )
                conn.commit()

    def cleanup(storage):
        with storage._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM rc_circuit_breakers WHERE namespace = %s",
                    (namespace,),
                )
                conn.commit()

    try:
        make()
    except Exception as e:
        print(f"  [SKIP] PostgreSQL unreachable ({e}); in-memory only")
        return {}
    return run_backend(
        "postgres", make, corrupt, supports_garbage_open_until=False, cleanup=cleanup
    )


def main():
    print(f"probe_malformed_state: DSN={DSN!r}")
    results = {}
    results.update(run_inmemory())
    results.update(run_postgres())
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
