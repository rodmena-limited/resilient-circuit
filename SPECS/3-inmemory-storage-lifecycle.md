# Ticket #3 — InMemoryStorage lifecycle gaps: unbounded entry growth and no delete/reset API

Origin: full-library resiliency evaluation focused on in-memory storage (Sisyphus,
2026-08-08). Live probe: 200,000 distinct keys written to `InMemoryStorage`; all
retained — no eviction, no TTL, no cap. `delete_state`/`clear` exist on no backend,
so a retired circuit (e.g. an OPEN that will never recover because the dependency
is gone) is pinned forever: memory in-process, a row in Postgres.

## EARS SPEC (system: CircuitBreakerStorage interface + InMemoryStorage)

- The `CircuitBreakerStorage` interface shall provide `delete_state(resource_key)`
  that removes the stored state for the key and reports whether a state was removed.
- `InMemoryStorage` shall implement `delete_state` to remove the key's entry from
  its store.
- `PostgresStorage` shall implement `delete_state` to delete the
  `(resource_key, namespace)` row.
- `InMemoryStorage` shall bound the number of stored resource keys to a
  configurable maximum (`max_entries`).
- While the stored state for a key is OPEN with an unexpired `open_until`,
  `InMemoryStorage` shall not evict that entry (a live protection signal must
  never be dropped to reclaim memory).
- When `InMemoryStorage` is at its entry cap, adding a new key shall evict the
  least-recently-used entry that is not live-OPEN.
- `InMemoryStorage` shall not grow without bound under churn of distinct resource
  keys (including the policy's default `anonymous_<id>` keys).

## Scope confirmation (post-evaluation, pre-fix)

Split across backends: unbounded **memory** growth + eviction/cap is
`InMemoryStorage`-only; the missing delete/reset API affects **both** backends
(Postgres rows accumulate forever too) and the interface fix spans
`InMemoryStorage` + `PostgresStorage`. There is no SQLite backend in the library.

## Design notes / regression constraints

- Evicting a non-live entry is semantically equivalent to first-time load: a
  CLOSED/HALF_OPEN/expired-OPEN key re-creates as CLOSED on the next call, which
  is exactly the no-stored-state path. The only invariant that must never be
  sacrificed is the live-OPEN entry (the ticket #1/#2 guard semantics).
- Existing tests to keep green: `test_storage_atomicity.py`, `test_storage_persistence.py`,
  `tests/test_circuit_breaker.py` (default-key policies must keep working).
- Live probe must be persisted under `audit/evaluations/` (shown RED against
  pre-fix code, GREEN after the fix), matching the ticket #1/#2 probe discipline.
