# Ticket #1 — PostgresStorage cross-process write race

Origin: auditor report from the bulkman team (agent-mail thread `thr-f029a7785ccf47ebb6bd`).
Defect: `get_state()`'s `FOR UPDATE` lock dies with its own connection; `set_state()` opens a
fresh connection; the load → decide → save cycle is last-writer-wins across processes. A
process holding a stale local CLOSED clobbered another process's persisted OPEN, silently
erasing the protection signal. Two simultaneous openers also race on `open_until`.

## EARS SPEC (system: resilient_circuit storage layer + CircuitProtectorPolicy persistence)

- The `CircuitBreakerStorage` interface shall provide an atomic read-modify-write operation
  `update_state(resource_key, mutator)` that loads current state, applies the mutator, and
  persists its result as one atomic unit.
- `PostgresStorage.update_state` shall perform load, mutate, and persist on a single
  connection in a single transaction, holding a per-key advisory transaction lock plus
  `SELECT ... FOR UPDATE`, so concurrent read-modify-write cycles for the same
  `(resource_key, namespace)` serialize — including when the row does not exist yet.
- `InMemoryStorage.update_state` shall perform the same cycle atomically under a
  process-local lock.
- If the stored state is OPEN with an unexpired `open_until`, then `set_state` shall refuse
  the write entirely (a live OPEN row is immutable to blind writers: stale CLOSED/HALF_OPEN
  cannot erase the protection signal, and a second OPEN cannot move the stored cooldown
  end — first opener wins).
- When the stored `open_until` has expired, `set_state` shall accept any transition
  (recovery OPEN → HALF_OPEN → CLOSED must not be blocked by the guard — the cap must work
  in both directions).
- `set_state` shall return whether the write was applied, so a refused write is
  distinguishable from an applied one.
- When a state write is refused because the stored circuit is live-OPEN, the
  `CircuitProtectorPolicy` shall reload and adopt the stored state, so the refusing process
  honors the shared protection signal on subsequent calls.
- `get_state` shall not take row locks it cannot keep past the method return (drop
  `FOR UPDATE` and the false atomicity docstring).
- The live multiprocess reproduction (stale-CLOSED clobber; concurrent openers racing on
  `open_until`) shall exist as a runnable probe under `audit/evaluations/`, shown RED
  against pre-fix code and GREEN after the fix.

## Out of scope (tracked as ticket #2)

Per-call distributed admission: the policy evaluates admission against locally cached state
between saves, so a process that never writes never learns of a peer's OPEN. Ticket #1 only
narrows this (adoption on refused write); the full fix is a per-call refresh / TTL-cached
read design decision.

## Notes

- Timestamp convention: the schema stores naive local-time `TIMESTAMP` written via
  `time.localtime()`. The guard's "unexpired" comparison uses a now-parameter formatted the
  same way by the writer, keeping clock semantics consistent with the existing schema.
  Cross-host clock skew is a pre-existing property of the schema, unchanged here.
