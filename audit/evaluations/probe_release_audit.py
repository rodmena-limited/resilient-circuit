"""Release audit probes for 0.5.0 (commits 2fd13e8, 4a7f2dc).

Falsifies claims that the live-OPEN write guard and per-call admission refresh
are pure improvements. Each scenario drives the library through its PUBLIC API
only (CircuitProtectorPolicy / CircuitState / storage API) -- never raw SQL.

  A1  administrative reset   -- `policy.status = CircuitState.CLOSED` is a public,
                               exported API. It must actually reset an OPEN
                               circuit. Post-fix the live-OPEN guard refuses the
                               write and the policy re-adopts OPEN, so the reset
                               silently evaporates.
  A2  timezone skew          -- two processes in different TZs must agree on when
                               a peer's OPEN expires. open_until is stored as a
                               NAIVE local-time string and read back as local
                               time, so a reader east of the writer sees the
                               cooldown as already expired and admits traffic
                               the breaker is supposed to block.
  A3  admission cost         -- the default admission_refresh_interval must
                               keep the pre-admission storage read amortized,
                               and must cost ~nothing per REJECTED call while
                               the circuit is OPEN (an un-throttled refresh
                               loads the state store in proportion to the
                               traffic a dependency outage generates). The
                               opt-in interval=None must still refresh every
                               call for instant peer-OPEN propagation.

History (each reproduced live against a real PostgreSQL):
  cbe4bb9 (pre-0.5.0):  A1 PASS, A2 FAIL, A4 FAIL, A3 n/a (no refresh existed)
  4a7f2dc (0.5.0):      A1 FAIL, A2 FAIL, A4 FAIL, A3 FAIL (2.0 conn/call,
                        1.0 per rejected call -- default was interval=None)
  0.6.0:                A1 FAIL, A2 PASS, A4 PASS (TIMESTAMPTZ + explicit UTC),
                        A3 PASS (default is now DEFAULT_ADMISSION_REFRESH_INTERVAL)

A1 is a KNOWN, DOCUMENTED behavior change, not an open defect: since 0.5.0 the
live-OPEN write guard makes `policy.status = CircuitState.CLOSED` a silent
no-op on an open circuit, and administrative reset goes through
`storage.update_state()` instead. The scenario is retained because the failure
mode is silent (the assignment returns normally); if the API ever grows a
loud failure or a supported reset, this probe should go green or be updated.

Run: python3 audit/evaluations/probe_release_audit.py
Env: RC_PROBE_DSN (default "dbname=resilient_circuit_test")
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


_UNSET = object()


def make_policy(namespace, key, cooldown_s=60.0, storage=None, refresh=_UNSET):
    from resilient_circuit.circuit_breaker import CircuitProtectorPolicy

    kwargs = {}
    if refresh is not _UNSET:
        kwargs["admission_refresh_interval"] = refresh
    return CircuitProtectorPolicy(
        resource_key=key,
        storage=storage if storage is not None else make_storage(namespace),
        cooldown=timedelta(seconds=cooldown_s),
        failure_limit=Fraction(1, 1),
        **kwargs,
    )


def trip_open(policy):
    """Drive one failing protected call so the breaker opens."""
    from resilient_circuit.exceptions import ProtectedCallError

    @policy
    def boom():
        raise RuntimeError("dependency down")

    try:
        boom()
    except ProtectedCallError:
        return "rejected"
    except RuntimeError:
        return "executed"


def call_once(policy):
    """One successful protected call; report whether it was admitted."""
    from resilient_circuit.exceptions import ProtectedCallError

    ran = []

    @policy
    def ok():
        ran.append(1)
        return "ok"

    try:
        ok()
        return "admitted", len(ran)
    except ProtectedCallError:
        return "rejected", len(ran)


# ------------------------------------------------------------------ A2 child

def a2_writer(ns, key, tz, out):
    """Open the circuit while running in timezone `tz`."""
    logging.disable(logging.CRITICAL)
    os.environ["TZ"] = tz
    time.tzset()
    policy = make_policy(ns, key, cooldown_s=300.0)
    trip_open(policy)
    out.put(("writer", policy._status.status_type.value,
             getattr(policy._status, "open_until_timestamp", 0)))


def a2_reader(ns, key, tz, out):
    """In a different timezone, see whether the peer's OPEN is honored."""
    logging.disable(logging.CRITICAL)
    os.environ["TZ"] = tz
    time.tzset()
    storage = make_storage(ns)
    seen = storage.get_state(key)
    policy = make_policy(ns, key, cooldown_s=300.0, storage=storage)
    outcome, executions = call_once(policy)
    out.put(("reader", outcome, executions,
             seen["state"] if seen else None,
             seen["open_until"] if seen else 0))


def a4_writer(ns, key, tz, cooldown_s, out):
    """Open a SHORT-cooldown circuit while running in timezone `tz`."""
    logging.disable(logging.CRITICAL)
    os.environ["TZ"] = tz
    time.tzset()
    policy = make_policy(ns, key, cooldown_s=cooldown_s)
    trip_open(policy)
    out.put(("w4", getattr(policy._status, "open_until_timestamp", 0)))


def a4_reader(ns, key, tz, sleep_s, cooldown_s, out):
    """After the cooldown has long expired, a peer must be admitted again."""
    logging.disable(logging.CRITICAL)
    os.environ["TZ"] = tz
    time.tzset()
    time.sleep(sleep_s)
    policy = make_policy(ns, key, cooldown_s=cooldown_s)
    out.put(("r4",) + call_once(policy))


def run():
    results = {}
    run_id = uuid.uuid4().hex[:8]

    # --- A1: administrative reset of a live OPEN --------------------------
    from resilient_circuit.circuit_breaker import CircuitStatus
    from resilient_circuit.storage import InMemoryStorage

    detail_bits = []
    a1_ok = True
    for label, storage in (
        ("InMemory", InMemoryStorage()),
        ("Postgres", make_storage(f"probe-a1-{run_id}")),
    ):
        policy = make_policy(
            f"probe-a1-{run_id}", "shared-dep", cooldown_s=300.0, storage=storage
        )
        trip_open(policy)
        before = policy.status.value

        # (a) The documented behavior: assigning CLOSED over a live OPEN is
        #     REFUSED by the write guard, and does so SILENTLY -- the
        #     assignment returns normally, which is why this is worth pinning.
        raised = None
        try:
            policy.status = CircuitStatus.CLOSED
        except Exception as e:  # noqa: BLE001 - any raise is a contract change
            raised = type(e).__name__
        local_after = policy.status.value
        stored_after = storage.get_state("shared-dep")
        stored_state = stored_after["state"] if stored_after else None
        refused_silently = (
            raised is None and local_after == "OPEN" and stored_state == "OPEN"
        )

        # (b) The RELEASE direction: the documented reset path must work, and
        #     a fresh policy must then be admitted. A guard that only ever
        #     blocks is how a breaker stays shut forever.
        storage.update_state(
            "shared-dep",
            lambda _cur: {"state": "CLOSED", "failure_count": 0, "open_until": 0},
        )
        reset_state = storage.get_state("shared-dep")
        fresh = make_policy(
            f"probe-a1-{run_id}", "shared-dep", cooldown_s=300.0, storage=storage
        )
        outcome, _executions = call_once(fresh)
        reset_works = (
            reset_state is not None
            and reset_state["state"] == "CLOSED"
            and outcome == "admitted"
        )

        ok = refused_silently and reset_works
        a1_ok = a1_ok and ok
        detail_bits.append(
            f"{label}: tripped {before}; status=CLOSED refused silently="
            f"{refused_silently} (raised={raised}, local={local_after}, "
            f"stored={stored_state}); update_state reset -> "
            f"stored={reset_state['state'] if reset_state else None}, "
            f"fresh-call={outcome}"
        )
    results["A1 reset contract: status= refused silently, update_state works"] = (
        a1_ok,
        "; ".join(detail_bits)
        + " (documented since 0.5.0: administrative reset goes through "
        "update_state(), not the status setter)",
    )

    # --- A2: timezone skew between peers ----------------------------------
    ns = f"probe-a2-{run_id}"
    key = "shared-dep"
    make_storage(ns)  # serialize DDL before children
    q = mp.Queue()
    pw = mp.Process(target=a2_writer, args=(ns, key, "UTC", q))
    pw.start()
    pw.join(60)
    pr = mp.Process(target=a2_reader, args=(ns, key, "Asia/Tehran", q))
    pr.start()
    pr.join(60)
    msgs = {}
    while not q.empty():
        m = q.get()
        msgs[m[0]] = m[1:]
    w = msgs.get("writer", ("?", 0))
    r = msgs.get("reader", ("?", -1, "?", 0))
    reader_outcome, reader_execs, reader_seen_state, reader_seen_ou = r
    skew = reader_seen_ou - w[1] if w[1] else 0
    a2_ok = reader_outcome == "rejected" and reader_execs == 0
    results["A2 peer OPEN honored across timezone skew"] = (
        a2_ok,
        f"writer(TZ=UTC) ended {w[0]} open_until={w[1]:.0f}; "
        f"reader(TZ=Asia/Tehran) read state={reader_seen_state} "
        f"open_until={reader_seen_ou:.0f} (skew {skew:+.0f}s); "
        f"reader call {reader_outcome} with {reader_execs} execution(s) "
        f"(must be rejected with 0)",
    )

    # --- A4: release direction of the same skew (must not stick open) -----
    # The guard must block when it should AND release when it should. A writer
    # in a timezone AHEAD of the reader writes an open_until the reader reads
    # as far in the future, so a 3s cooldown can pin the breaker shut for the
    # whole TZ offset -- a self-inflicted outage of the protected dependency.
    ns = f"probe-a4-{run_id}"
    key = "shared-dep"
    make_storage(ns)
    q = mp.Queue()
    pw = mp.Process(target=a4_writer, args=(ns, key, "Asia/Tehran", 3.0, q))
    pw.start()
    pw.join(60)
    pr = mp.Process(target=a4_reader, args=(ns, key, "UTC", 6.0, 3.0, q))
    pr.start()
    pr.join(60)
    msgs = {}
    while not q.empty():
        m = q.get()
        msgs[m[0]] = m[1:]
    w4 = msgs.get("w4", (0,))
    r4_outcome, r4_execs = msgs.get("r4", ("?", -1))
    a4_ok = r4_outcome == "admitted"
    results["A4 breaker releases after cooldown across timezone skew"] = (
        a4_ok,
        f"writer(TZ=Asia/Tehran) opened with cooldown=3s (open_until={w4[0]:.0f}); "
        f"reader(TZ=UTC) called 6s later -> {r4_outcome} with {r4_execs} "
        f"execution(s) (must be admitted; 'rejected' = stuck open for the TZ offset)",
    )

    # --- A3: storage cost of admission ------------------------------------
    # PostgresStorage._get_connection() is unpooled: one psycopg.connect per
    # storage operation. The state SAVE after each completed call is a
    # pre-existing 1 connection/call and is NOT what this scenario polices.
    # What it polices is the ADMISSION refresh, which the default interval must
    # keep amortized -- and in particular the OPEN circuit, where there is no
    # save at all and an un-throttled refresh would put one connection per
    # *rejected* call on the state store, in proportion to the very traffic a
    # dependency outage is generating.
    import resilient_circuit.storage as storage_mod

    def measure(label, refresh, trip, calls=20):
        ns_m = f"probe-a3-{label}-{run_id}"
        storage_m = make_storage(ns_m)
        policy = make_policy(
            ns_m, "hot-path", cooldown_s=300.0, storage=storage_m, refresh=refresh
        )
        if trip:
            trip_open(policy)
        counter = {"n": 0}
        real_connect = storage_mod.psycopg.connect

        def counting_connect(*a, **kw):
            counter["n"] += 1
            return real_connect(*a, **kw)

        storage_mod.psycopg.connect = counting_connect
        try:
            t0 = time.perf_counter()
            for _ in range(calls):
                call_once(policy)
            elapsed = time.perf_counter() - t0
        finally:
            storage_mod.psycopg.connect = real_connect
        return counter["n"] / calls, elapsed * 1000 / calls

    healthy_default, ms_default = measure("healthy", _UNSET, trip=False)
    healthy_percall, ms_percall = measure("healthy-none", None, trip=False)
    open_default, _ = measure("open", _UNSET, trip=True)
    open_percall, _ = measure("open-none", None, trip=True)

    # Both directions: the default must bound admission cost on the healthy
    # path AND cost ~nothing while the circuit is OPEN, while the opt-in
    # per-call mode must still actually refresh every call.
    a3_ok = (
        healthy_default <= 1.25  # save (1.0) + amortized refresh
        and open_default <= 0.25  # rejected calls must not hit storage
        and healthy_percall >= 1.75  # None still refreshes every call
    )
    results["A3 storage cost of admission (default vs per-call)"] = (
        a3_ok,
        f"healthy path: default {healthy_default:.2f} conn/call "
        f"({ms_default:.1f} ms) vs interval=None {healthy_percall:.2f} conn/call "
        f"({ms_percall:.1f} ms); circuit OPEN: default {open_default:.2f} "
        f"conn/rejected-call vs interval=None {open_percall:.2f}. "
        f"Required: default <=1.25 healthy, <=0.25 while OPEN, None >=1.75",
    )

    return results


def main():
    print(f"probe_release_audit: DSN={DSN!r}")
    results = run()
    red = False
    for name, (ok, detail) in results.items():
        tag = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        if ok is False:
            red = True
        print(f"  [{tag}] {name}\n         {detail}")
    print(f"probe result: {'RED (defect present)' if red else 'GREEN'}")
    return 1 if red else 0


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    sys.exit(main())
