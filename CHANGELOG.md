# Changelog
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
