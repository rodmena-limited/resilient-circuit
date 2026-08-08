# Changelog
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.6.0] - 2026-08-08

### Fixed
- **Protected calls no longer crash on malformed stored state**: a corrupt
  stored row (unknown state value, non-numeric `failure_count`/`open_until`)
  previously raised `ValueError` out of the protected call because the
  pre-admission refresh path guarded `get_state()` but not state adoption.
  The policy now validates stored state on load and refresh, logs and ignores
  malformed rows (falling back to CLOSED), and self-heals the row on the next
  successful write. Backend-agnostic: reproduced and fixed for both
  `InMemoryStorage` and `PostgresStorage` (live probe
  `audit/evaluations/probe_malformed_state.py`).
- **`CircuitProtectorPolicy` is now thread-safe**: status decisions,
  transitions and state saves are serialized on a per-policy re-entrant lock
  (never held across the protected callable, so calls stay concurrent), and a
  stale in-flight success recorded while the circuit is OPEN no longer
  transitions OPEN → HALF_OPEN, so it can no longer shortcut the cooldown.
  Previously, threads sharing one policy could interleave
  `mark_success`/`mark_failure` on the same status object and execute the
  protected callable after the circuit had tripped (live probe
  `audit/evaluations/probe_policy_thread_safety.py`).
- **`InMemoryStorage` no longer grows without bound**: an entry cap
  (`max_entries`, default 8192) with least-recently-used eviction drops the
  oldest non-live entry when the cap is reached. A live OPEN (unexpired
  `open_until`) is never evicted — a protection signal is never dropped to
  reclaim memory, even if the cap is temporarily exceeded. Evicting a
  non-live entry is semantically equivalent to first-time load (re-created
  as CLOSED). Live probe `audit/evaluations/probe_inmemory_lifecycle.py`.

### Added
- `CircuitBreakerStorage.delete_state(resource_key)`: removes the stored
  state for a key, returning whether a state was removed. Implemented for
  both backends; the base class provides a safe no-op (returns False) for
  third-party backends. Retired circuits (e.g. an OPEN that will never
  recover) can now be cleaned up.
- `backend_name` attribute on every storage backend (`"in-memory"`,
  `"postgres"`, `"unknown"` for the base class) so callers can tell whether
  state is shared across processes or process-local.
- `create_storage()` now emits a prominent `RuntimeWarning` when PostgreSQL
  was requested (`RC_DB_*` set) but is unavailable and the library silently
  falls back to in-memory storage — a distributed deployment can no longer
  degrade to per-process isolation invisibly. The fallback behavior itself
  is unchanged.

### Changed
- **`admission_refresh_interval` now defaults to 1 second** (
  `DEFAULT_ADMISSION_REFRESH_INTERVAL`) instead of `None`. In 0.5.0 the
  default refreshed shared state on *every* protected call; since
  `PostgresStorage` opens an unpooled connection per operation, that cost a
  connect+SELECT per call — and, because a rejected call performs no state
  save, one connection per **rejected** call while the circuit was OPEN. A
  dependency outage therefore generated sustained connection churn against
  the state store in proportion to the traffic the breaker was shedding,
  making the breaker its own failure domain. Measured against live
  PostgreSQL (`audit/evaluations/probe_release_audit.py`, scenario A3):

  | | healthy path | while OPEN |
  |---|---|---|
  | 0.5.0 (`None`) | 2.00 conn/call, 8.8 ms | 1.00 conn/rejected-call |
  | 0.6.0 (1 s) | 1.05 conn/call, 4.1 ms | 0.00 conn/rejected-call |

  The trade-off is propagation delay: a peer's OPEN is now honored within one
  interval rather than on the very next call. Pass
  `admission_refresh_interval=None` (or `timedelta(0)`) to restore 0.5.0's
  refresh-every-call behavior and instant propagation.
- `InMemoryStorage(max_entries=8192)` — configurable entry cap (pass `None`
  for the previous unbounded behavior). `_states` is now an `OrderedDict`
  used as an LRU; `get_state` marks keys recently used.

### Fixed
- **PostgreSQL timestamps are now timezone-independent**: `open_until` is
  written as explicit UTC into a `TIMESTAMPTZ` column, and the live-OPEN
  guard compares against UTC — a peer in any timezone reads the same
  instant. Previously the schema mixed naive-local `TIMESTAMP` writes with a
  session-timezone-dependent guard. The runtime migrator upgrades legacy
  tables in place (adds `namespace`/`execution_log`, installs the composite
  `(resource_key, namespace)` key, converts naive `TIMESTAMP` `open_until`
  to `TIMESTAMPTZ`, preserving stored rows). Verified live by
  `audit/evaluations/probe_schema_migration.py`.
- **The CLI and the runtime can no longer drift apart**: both create the
  table from the same schema definition
  (`resilient_circuit.storage._RC_TABLE_DDL`); previously the CLI created
  `TIMESTAMPTZ` while the runtime created `TIMESTAMP`.
- **Schema setup runs once per process** instead of issuing DDL on every
  `PostgresStorage` construction; the migration is serialized across
  processes by an advisory lock and is idempotent.
- **`ExponentialDelay.for_attempt` no longer overflows** at large attempt
  counts (the delay is now capped at each growth step instead of after the
  multiplication) and never returns below `min_delay` once jitter is
  applied; `factor < 1` and `max_delay < min_delay` are rejected.
- **`BinaryCircularBuffer` is iterable**: `list(protector.execution_log)` —
  documented in the README but previously raised `TypeError` — now works,
  and iteration/statistics are consistent under concurrent `add` calls.
- **`CircuitProtectorPolicy` tests are hermetic**: the policy-logic tests
  pin `InMemoryStorage` explicitly; previously they ran against shared
  PostgreSQL state through fixed resource keys whenever `RC_DB_*` was set,
  which made the suite order- and load-dependent (flaky).
- **Removed `setup_postgres.sh`**: it created a table named
  `hw_circuit_breakers` that the library never reads, used `HW_DB_*` env
  vars the library ignores, and referenced a package name that no longer
  exists — a footgun that gave false confidence. Use
  `resilient-circuit-cli pg-setup` instead.

### Added
- `resilient_circuit.__version__` (available as
  `from resilient_circuit import __version__`).
- Live schema-migration probe `audit/evaluations/probe_schema_migration.py`
  (destructive; requires `AUDIT_ALLOW_DESTRUCTIVE=1`).

### Changed
- The CLI console command is `resilient-circuit-cli` (matching the docs and
  the `argparse` program name; the previous `resilient-circuit` entry point
  name was inconsistent with both).
- `Makefile` rewritten for the current toolchain (`ruff format`, `ruff
  check`, `mypy --strict`, `pytest`); it previously referenced a
  non-existent package directory and the removed `poetry`/`pylint` flow.
- **Toolchain consolidated**: `ruff` is the single formatter and linter
  (the `black`/`isort` roles and their dev dependencies and config sections
  are removed), and its floor is pinned to `>=0.16.0` — the version that
  also formats Python code blocks inside markdown — so the format gate is
  reproducible across environments. The test suite runs warning-free
  (verified with `pytest -W error`).

### Known limitations (unchanged)
- Admission is point-in-time: a peer opening the circuit between the refresh
  and the protected call's execution is inherent TOCTOU.
- Concurrent execution-log buffers are last-writer-wins, not merged.
- Timestamps are stored as UTC instants; hosts whose clocks disagree will
  still disagree about a cooldown's expiry (cross-host clock skew).

## [0.5.0] - 2026-08-06

### Fixed
- **Cross-process write race in PostgresStorage** (reported by the bulkman audit):
  the load → decide → save cycle was last-writer-wins across processes, so a
  process holding a stale local CLOSED could clobber a stored OPEN and silently
  erase the protection signal, and two simultaneous openers raced on
  `open_until`. `get_state()`'s `SELECT ... FOR UPDATE` only ever locked the row
  for the lifetime of its own connection, so it provided no atomicity at all.

### Added
- `CircuitBreakerStorage.update_state(resource_key, mutator)`: atomic
  read-modify-write. PostgresStorage runs load → mutate → persist on one
  connection in one transaction, holding a per-key advisory transaction lock
  (`pg_advisory_xact_lock`) plus `SELECT ... FOR UPDATE`, so concurrent cycles
  serialize even when the row does not exist yet. InMemoryStorage does the same
  under a process-local lock. The base class provides a non-atomic fallback for
  third-party backends.
- Live multiprocess reproduction probes `audit/evaluations/probe_write_race.py`
  and `audit/evaluations/probe_distributed_admission.py` (each shown red
  against the pre-fix code, green against 0.5.0) plus in-process regression
  tests (`tests/test_storage_atomicity.py`,
  `tests/test_distributed_admission.py`).
- **Distributed admission**: `CircuitProtectorPolicy` now refreshes its view
  from shared storage before admitting each protected call, so a process
  honors a peer's OPEN immediately — the failing dependency is not hit even
  once by processes that never observed a failure themselves. New
  `admission_refresh_interval: timedelta` parameter throttles the refresh on
  hot paths (between refreshes admission uses the local view); default is
  refresh-on-every-call. On a storage read failure the local view is kept
  (fail-open) — a storage outage never takes down the caller.

### Changed
- **`set_state()` now returns `bool` and refuses stale writes**: when the stored
  state is OPEN with an unexpired `open_until`, a blind write is refused
  (returns `False`) — a stale CLOSED/HALF_OPEN can no longer erase a live
  protection signal, and a later opener can no longer move the stored cooldown
  end (first opener wins). Once `open_until` expires, all writes are accepted
  again, so recovery (OPEN → HALF_OPEN → CLOSED) is never blocked. Deliberate
  overrides (administrative reset) go through `update_state()`, which writes
  unguarded because its mutator saw the current state.
- `CircuitProtectorPolicy` adopts the stored state when its own write is
  refused: a process whose stale success write is rejected reloads the stored
  OPEN and starts rejecting calls itself instead of continuing to hammer the
  failing dependency.
- `get_state()` no longer issues `FOR UPDATE` (the lock died with the method's
  own connection; the docstring claiming atomicity was false) and
  InMemoryStorage now returns defensive copies instead of aliases of its
  internal state.
- `open_until` is now stored with microsecond precision (was truncated to
  whole seconds); sub-second cooldowns survive the storage round-trip, which
  matters now that peers adopt each other's stored `open_until`.
- `on_status_change` now also fires when a breaker adopts a peer's stored
  state with a different status (via the pre-admission refresh or a refused
  write), not only on locally driven transitions.

### Known limitations
- Admission is point-in-time: a peer opening the circuit between the refresh
  and the protected call's execution is inherent TOCTOU.
- Concurrent execution-log buffers are last-writer-wins, not merged; failure
  evidence recorded by two processes between each other's saves can be lost
  (protection-state transitions themselves are guarded, as above).
- The schema stores naive local-time timestamps; the guard compares against the
  writer's clock, so cross-host clock skew remains a pre-existing property of
  the schema.

## [0.4.0] - 2025-11-21

### Added
- **Namespace Support for Circuit Breaker Isolation**: Added `namespace` parameter to `CircuitProtectorPolicy` and `create_storage()` to enable per-workflow or per-tenant isolation
- **PostgreSQL Composite Primary Key**: Changed `rc_circuit_breakers` table to use composite key `(resource_key, namespace)` for true database-level isolation
- **Automatic Schema Migration**: PostgresStorage now automatically migrates from old single-column PK to new composite PK on first connection
- **Environment Variable Support**: Added `RC_NAMESPACE` environment variable to set default namespace
- **Test Isolation**: Parallel tests can now run without shared state conflicts using unique namespaces

### Changed
- **Breaking**: PostgreSQL schema changed to use `(resource_key, namespace)` composite primary key instead of `resource_key` alone
- Updated `PostgresStorage.__init__()` to accept `namespace` parameter (defaults to "default")
- Updated all queries to filter by both `resource_key` AND `namespace`
- Enhanced logging to include namespace information

### Fixed
- Fixed test failures in parallel execution due to circuit breaker global state
- Fixed `pytest-mock` dependency issue in `test_retry.py` (replaced `mocker` with `monkeypatch`)
- Fixed PostgreSQL env var test in `test_storage_persistence.py`
- Fixed mypy type errors in `circuit_breaker.py` and `storage.py`
- Fixed type annotations for `_load_state()`, `_save_state()`, and `InMemoryStorage.__init__()`

### Technical Details
- Added 3 new indexes: `idx_rc_circuit_breakers_namespace`, `idx_rc_circuit_breakers_key_namespace`
- Migration handles both new installations and upgrades from v0.3.x
- All 86 tests passing with 5 skipped (PostgreSQL tests require database)
- Reduced mypy strict mode errors from 21 to 4 (cli.py only)

## [0.3.1] - 2024-11-18

### Added
- Complete rewrite of documentation with new examples
- Integration with Highway Workflow Engine
- Enhanced API for better developer experience
- Comprehensive usage examples and best practices

## [0.2.0] - 2025-11-10
### Added
- Initial release with circuit breaker and retry patterns
