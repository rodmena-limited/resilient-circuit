# Ticket #7 — Release-audit sweep (pre-1.0.0 readiness)

Origin: full pre-release audit (Sisyphus, 2026-08-08) commissioned so an
independent audit finds no open problems. All findings below were CONFIRMED
live, fixed in this round, and re-verified.

## EARS SPEC (system: resilient_circuit, release readiness)

- `ExponentialDelay.for_attempt` shall never overflow (delay capped at each
  growth step), shall never return below `min_delay` once jitter is applied,
  and shall reject `factor < 1` and `max_delay < min_delay` at construction.
- `GenericCircularBuffer` shall be iterable (`list(buffer)` works — the README
  documented it) and iteration/statistics shall be consistent under
  concurrent `add`.
- `PostgresStorage` shall store `open_until` as an explicit-UTC `TIMESTAMPTZ`,
  compare the live-OPEN guard in UTC, and migrate legacy tables (pre-namespace
  single-column PK, naive `TIMESTAMP`) in place without losing stored rows.
- The CLI and the runtime migrator shall create the table from the same schema
  definition so they can never drift apart.
- `PostgresStorage` shall run schema DDL once per process and serialize the
  migration across processes (advisory lock, idempotent).
- The console command shall be `resilient-circuit-cli` consistently across
  `pyproject.toml`, the `argparse` program name, and the docs.
- The distribution shall not ship artifacts referencing a non-existent table
  (`hw_circuit_breakers`), env vars (`HW_DB_*`), or package name — removed
  `setup_postgres.sh` and corrected `env.example`.
- Policy-logic tests shall be hermetic (explicit storage) so the suite is
  order- and load-independent.
- `resilient_circuit` shall expose `__version__`.

## Evidence (all CONFIRMED live)

- `ExponentialDelay.for_attempt(2000)` raised `OverflowError`; jitter returned
  delays below `min_delay`.
- `list(protector.execution_log)` raised `TypeError` (no `__iter__`) despite
  the README documenting it.
- The CLI created `TIMESTAMPTZ` while the runtime created `TIMESTAMP`;
  `_ensure_table_exists` issued full DDL on every construction.
- `setup_postgres.sh` created `hw_circuit_breakers` (never read), used
  `HW_DB_*` (never read); `env.example` documented `HW_DB_*`.
- `tests/test_circuit_breaker.py` was order- and load-dependent with
  `RC_DB_*` set: shared PostgreSQL state through fixed resource keys made the
  suite flaky under load (reproduced: intermittent failures only in the full
  suite, green in isolation).
- `pyproject.toml` entry (`resilient-circuit`), `argparse` prog
  (`highway-circutbreaker-cli`) and docs (`resilient-circuit-cli`) named three
  different commands.

## Verification

- `audit/evaluations/probe_schema_migration.py` (destructive, opt-in):
  G1 legacy migration preserves rows, G1b schema TIMESTAMPTZ + composite PK,
  G2 microsecond round-trip, G3 guard both directions + first-opener-wins,
  G4 TZ independence (+03:30 session reads the same instant), G5 two-process
  concurrent migration — all PASS.
- 157 pytest (×3 runs), `mypy --strict` 0 issues, `ruff check` + `ruff format`
  clean, wheel built + installed, console script verified, sdist contains no
  stale artifacts.
