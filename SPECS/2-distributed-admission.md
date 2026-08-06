# Ticket #2 — Distributed admission: honor a peer's OPEN before executing the call

Found while fixing ticket #1 (bulkman audit). Ticket #1 made persistence safe (a stale
writer cannot clobber a live OPEN, and a refused writer adopts the stored state), but
admission was still evaluated against the state loaded at construction: a process that
never writes never learns of a peer's OPEN, and a stale process still executes its
protected callable once before its refused write triggers adoption.

## EARS SPEC (system: CircuitProtectorPolicy)

- When a protected call is admitted, the `CircuitProtectorPolicy` shall refresh its view
  from shared storage before `validate_execution`, so admission is evaluated against the
  stored state.
- While the stored circuit is OPEN with unexpired cooldown, a process that never observed
  a failure and never wrote state shall reject protected calls WITHOUT executing the
  protected callable (zero executions, not one-then-adopt).
- Where `admission_refresh_interval` is configured, the policy shall refresh at most once
  per interval (monotonic clock) and use the local view between refreshes.
- If the storage read fails, then the policy shall keep its local view and admit per
  local state (fail-open, logged) — a storage outage must not take down the caller;
  matches the existing `_load_state`/`_save_state` convention.
- When a refresh adopts a state whose status type differs from the local one, the policy
  shall invoke `on_status_change(old, new)`.
- While an adopted OPEN is in effect, when the cooldown expires, the adopting process
  shall transition OPEN → HALF_OPEN and be able to CLOSE the circuit (recovery direction
  must still work).
- The live multiprocess reproduction (B never writes; A trips OPEN; B's next call must be
  rejected with 0 executions of B's callable) shall exist under `audit/evaluations/`,
  shown RED against commit `25cb4a3` (ticket-1 fix only) and GREEN after this fix.

## Design notes

- Refresh happens only in the protected-call path (the decorator), never in property
  getters — a property that performs I/O would be a trap.
- Default is refresh-on-every-call: configuring shared PostgreSQL storage is a request
  for distributed breaking, so correctness is the default and throttling is the opt-in
  (`admission_refresh_interval`). Note the library already pays one storage round-trip
  per call (`_save_state` after every execution), so the refresh at most doubles, not
  changes the order of, storage traffic.
- Admission remains point-in-time: a peer opening between refresh and execution is
  inherent TOCTOU and out of scope, as is merging concurrent execution-log buffers.
