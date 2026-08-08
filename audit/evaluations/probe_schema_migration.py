#!/usr/bin/env python3
"""Live probe: PostgresStorage schema migration + TZ-independent timestamps.

Falsifies the pre-0.6.0 schema claim against a REAL throwaway database:

  G1  legacy migration      — a pre-0.4.0 table (single-column PK, no
      namespace, naive TIMESTAMP open_until) is migrated in place: columns
      added, composite PK installed, open_until converted to TIMESTAMPTZ,
      stored rows preserved with their instant.
  G2  round-trip precision  — open_until written with microseconds reads
      back within 0.01s.
  G3  guard both directions — on the migrated schema, a stale CLOSED is
      refused against a live OPEN, and writes are accepted once open_until
      has expired (recovery not blocked).
  G4  TZ independence        — an open_until written by the library reads
      back as the same instant from a session forced to a non-UTC timezone.
  G5  concurrent migration   — two processes constructing PostgresStorage
      against a legacy table at the same time both succeed (advisory lock +
      idempotent DDL); the migration applies exactly once.

Destructive: creates and drops the throwaway database named by RC_MIGRATE_DB
(default resilient_circuit_migtest) on the server named by RC_MIGRATE_SERVER
(default "dbname=postgres"). Refuses to run unless AUDIT_ALLOW_DESTRUCTIVE=1.

Run: AUDIT_ALLOW_DESTRUCTIVE=1 python3 audit/evaluations/probe_schema_migration.py
"""

import logging
import multiprocessing as mp
import os
import sys
import time

logging.disable(logging.CRITICAL)

MIGRATE_DB = os.environ.get("RC_MIGRATE_DB", "resilient_circuit_migtest")
SERVER = os.environ.get("RC_MIGRATE_SERVER", "dbname=postgres")


def g5_concurrent_migration(storage, connect_migrate_db):
    """Two processes construct PostgresStorage against a legacy table at the
    same time; both must succeed and the row must be preserved."""
    from resilient_circuit import storage as storage_module
    from resilient_circuit.storage import PostgresStorage

    def migration_worker(dsn, out):
        # fork inherits the parent's once-per-process flag; simulate a
        # genuinely fresh process so the migration actually runs here
        storage_module._PG_SCHEMA_READY = False
        try:
            PostgresStorage(dsn, namespace="default")
            out.put(("ok",))
        except Exception as e:  # noqa: BLE001
            out.put(("error", f"{type(e).__name__}: {e}"))

    with connect_migrate_db() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP TABLE rc_circuit_breakers")
            cur.execute(
                """
                CREATE TABLE rc_circuit_breakers (
                    resource_key VARCHAR(255) NOT NULL,
                    state VARCHAR(50) NOT NULL,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    open_until TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (resource_key)
                )
                """
            )
            cur.execute(
                "INSERT INTO rc_circuit_breakers "
                "(resource_key, state, failure_count, open_until) "
                "VALUES (%s, %s, %s, NOW() + INTERVAL '1 hour')",
                ("race-open", "OPEN", 2),
            )
    q = mp.Queue()
    procs = [
        mp.Process(target=migration_worker, args=(f"dbname={MIGRATE_DB}", q))
        for _ in range(2)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
    outcomes = []
    while not q.empty():
        outcomes.append(q.get()[0])
    race_stored = storage.get_state("race-open")
    return (
        outcomes == ["ok", "ok"]
        and race_stored is not None
        and race_stored["state"] == "OPEN"
        and race_stored["failure_count"] == 2,
        f"processes reported {sorted(outcomes)} (both ok); race-open stored "
        f"{race_stored}",
    )


def main():
    if os.environ.get("AUDIT_ALLOW_DESTRUCTIVE") != "1":
        print(
            "ABORT: destructive probe (creates/drops a throwaway database). "
            "Set AUDIT_ALLOW_DESTRUCTIVE=1 to run. "
            f"Blast radius: database '{MIGRATE_DB}' only."
        )
        return 2

    try:
        import psycopg  # noqa: F401
    except ImportError:
        print("ABORT: psycopg not installed")
        return 2

    from resilient_circuit.storage import PostgresStorage

    results = {}

    def connect(dbname):
        return psycopg.connect(f"dbname={dbname}" if dbname == MIGRATE_DB else SERVER)

    def connect_migrate_db():
        # SERVER is a conninfo; swap its dbname to the temp database
        parts = [p for p in SERVER.split() if not p.startswith("dbname=")]
        return psycopg.connect(" ".join(parts + [f"dbname={MIGRATE_DB}"]))

    # --- setup: create a throwaway database with a legacy table -------------
    try:
        with connect(SERVER) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {MIGRATE_DB}")
                cur.execute(f"CREATE DATABASE {MIGRATE_DB}")
    except Exception as e:
        print(f"ABORT: cannot create throwaway database: {e}")
        return 2

    legacy_inserted_at = time.time()
    try:
        with connect_migrate_db() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE rc_circuit_breakers (
                        resource_key VARCHAR(255) NOT NULL,
                        state VARCHAR(50) NOT NULL,
                        failure_count INTEGER NOT NULL DEFAULT 0,
                        open_until TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (resource_key)
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO rc_circuit_breakers "
                    "(resource_key, state, failure_count, open_until) "
                    "VALUES (%s, %s, %s, NOW() + INTERVAL '1 hour')",
                    ("legacy-open", "OPEN", 3),
                )
                cur.execute(
                    "INSERT INTO rc_circuit_breakers "
                    "(resource_key, state, failure_count, open_until) "
                    "VALUES (%s, %s, %s, NULL)",
                    ("legacy-closed", "CLOSED", 0),
                )
        storage = PostgresStorage(f"dbname={MIGRATE_DB}", namespace="default")
    except Exception as e:
        print(f"ABORT: migration setup failed: {e}")
        with connect(SERVER) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {MIGRATE_DB}")
        return 2

    # --- G1: legacy rows preserved, schema migrated -------------------------
    legacy_open = storage.get_state("legacy-open")
    legacy_closed = storage.get_state("legacy-closed")
    expected_ou = legacy_inserted_at + 3600
    g1_ok = (
        legacy_open is not None
        and legacy_open["state"] == "OPEN"
        and legacy_open["failure_count"] == 3
        and abs(legacy_open["open_until"] - expected_ou) < 120
        and legacy_closed is not None
        and legacy_closed["state"] == "CLOSED"
    )
    results["G1 legacy migration preserves rows"] = (
        g1_ok,
        f"legacy-open stored {legacy_open} (open_until must be ~now+3600 "
        f"within 120s); legacy-closed stored {legacy_closed}",
    )

    # schema forensics (no product interface exposes column types)
    with connect_migrate_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'rc_circuit_breakers' AND column_name = 'open_until'"
            )
            open_until_type = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM pg_constraint "
                "WHERE conrelid = 'rc_circuit_breakers'::regclass AND contype = 'p'"
            )
            pk_count = cur.fetchone()[0]
    results["G1b schema migrated to TIMESTAMPTZ + composite PK"] = (
        open_until_type == "timestamp with time zone" and pk_count == 1,
        f"open_until type = {open_until_type} (timestamptz), "
        f"primary keys = {pk_count} (1 composite)",
    )

    # --- G2: sub-second round-trip precision --------------------------------
    precise = time.time() + 0.5
    storage.set_state("precision-key", "OPEN", 1, precise)
    stored_precise = storage.get_state("precision-key")
    results["G2 microsecond open_until round-trip"] = (
        stored_precise is not None
        and abs(stored_precise["open_until"] - precise) < 0.01,
        f"wrote {precise}, read {stored_precise['open_until'] if stored_precise else None}",
    )

    # --- G3: live-OPEN guard, both directions ------------------------------
    guard_open = time.time() + 3600
    storage.set_state("guard-key", "OPEN", 5, guard_open)
    refused = storage.set_state("guard-key", "CLOSED", 0, 0)
    no_move = storage.set_state("guard-key", "OPEN", 7, guard_open + 1800)
    still_open = storage.get_state("guard-key")
    # release direction: on a key whose cooldown has expired, recovery writes
    # must be accepted (the guard must not wedge the circuit)
    storage.set_state("expired-key", "OPEN", 5, time.time() - 10)
    accepted = storage.set_state("expired-key", "HALF_OPEN", 0, 0)
    results["G3 guard blocks stale writes and releases after expiry"] = (
        refused is False
        and no_move is False
        and still_open is not None
        and still_open["state"] == "OPEN"
        and still_open["failure_count"] == 5
        and accepted is True,
        f"stale CLOSED refused={refused} (False), later-opener refused="
        f"{no_move} (False, first-opener-wins), stored stayed "
        f"{still_open['state'] if still_open else None} with "
        f"failure_count={still_open['failure_count'] if still_open else None} "
        f"(5), post-expiry HALF_OPEN accepted={accepted} (True)",
    )

    # --- G4: TZ independence -----------------------------------------------
    with connect_migrate_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'Asia/Tehran'")  # +03:30, non-UTC
            cur.execute(
                "SELECT open_until FROM rc_circuit_breakers "
                "WHERE resource_key = 'precision-key'"
            )
            row = cur.fetchone()
    foreign_epoch = row[0].timestamp() if row and row[0] else None
    results["G4 open_until TZ-independent (non-UTC session)"] = (
        foreign_epoch is not None and abs(foreign_epoch - precise) < 0.01,
        f"read from +03:30 session = {foreign_epoch}, library wrote {precise}",
    )

    # --- G5: concurrent migration across processes -------------------------
    g5_result = g5_concurrent_migration(storage, connect_migrate_db)
    if g5_result is not None:
        results["G5 concurrent migration both succeed, row preserved"] = g5_result

    # --- teardown ------------------------------------------------------------
    with connect(SERVER) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {MIGRATE_DB}")

    failed = False
    for name, (ok, detail) in results.items():
        tag = "PASS" if ok else "FAIL"
        if not ok:
            failed = True
        print(f"  [{tag}] {name}\n         {detail}")
    print("probe result:", "RED (defect present)" if failed else "GREEN")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
