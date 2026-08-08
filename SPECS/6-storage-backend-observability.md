# Ticket #6 — Silent InMemory fallback when Postgres is unavailable

Origin: full-library resiliency evaluation (Sisyphus, 2026-08-08). `create_storage()`
with `RC_DB_*` set to an unreachable host returns `InMemoryStorage` after a single
`logger.error` line: a deployment that intends distributed breaking silently
degrades to per-process isolation. The fallback itself is pinned by
`test_should_fallback_to_inmemory_on_postgres_failure` and must be preserved; the
gap is that it is invisible to callers.

## EARS SPEC (system: create_storage + storage backends)

- The `CircuitBreakerStorage` returned by `create_storage` shall expose a backend
  identity (e.g. `backend_name` property) so callers can determine whether
  distributed (Postgres) or process-local (in-memory) storage is in effect.
- When PostgreSQL is requested (`RC_DB_*` present) but unavailable, `create_storage`
  shall emit a prominent warning (log + `warnings.warn`) before falling back to
  `InMemoryStorage`.
- The existing fallback behavior (returning `InMemoryStorage`) shall be preserved
  for backward compatibility.

## Regression constraints

- `test_should_fallback_to_inmemory_on_postgres_failure` stays green (fallback
  unchanged); only observability is added.
