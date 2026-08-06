# Changelog
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
- Live multiprocess reproduction probe `audit/evaluations/probe_write_race.py`
  (red against 0.4.4, green against 0.5.0) plus in-process regression tests
  (`tests/test_storage_atomicity.py`).

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

### Known limitations
- Distributed admission is still local between saves: a process that never
  writes never refreshes its view of a peer's OPEN (tracked as ticket #2; the
  refused-write adoption above narrows but does not close this).
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
