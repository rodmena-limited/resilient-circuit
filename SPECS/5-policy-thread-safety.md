# Ticket #5 — CircuitProtectorPolicy is not thread-safe

Origin: full-library resiliency evaluation (Sisyphus, 2026-08-08). Live probe: 3
success threads + 1 failure thread on one shared policy (`failure_limit=1/1`,
`cooldown=60s`); the protected callable executed **2 times while storage already
held OPEN**. The storage guard kept the *stored* state OPEN, but the *decision*
path (`validate_execution` → execute → `mark_*` → `_save_state`) is not atomic:
`mark_success`/`mark_failure` mutate shared status objects and `self._status` is
swapped mid-sequence. This bites exactly where InMemoryStorage is the deployment:
one policy object shared across threads in a single process.

## EARS SPEC (system: CircuitProtectorPolicy)

- While a protected call is admitted, executed and recorded, the
  `CircuitProtectorPolicy` shall serialize status decisions, transitions and
  state saves on a per-policy lock, so concurrent threads sharing one policy
  cannot interleave `mark_success`/`mark_failure` on the same status object or
  swap `_status` mid-sequence.
- The per-policy lock shall not be held across the execution of the protected
  callable (concurrent calls to the protected resource remain concurrent).
- The `on_status_change` callback shall not deadlock when it re-enters the
  policy from within a transition (re-entrant lock, or callback invoked outside
  the lock).
- When a live-OPEN transition races a concurrent success, the stored state shall
  remain OPEN and the policy shall adopt it (no regression to the ticket #1/#2
  guard semantics).

## Scope confirmation (post-evaluation, pre-fix)

**Backend-agnostic, NOT in-memory-only.** The race is in the policy layer
(shared `_status` mutated by concurrent `mark_success`/`mark_failure`; the
`validate_execution` → execute → mark → save cycle is non-atomic) and reproduces
with any storage backend when threads share one policy object. It is merely most
visible in the default single-process InMemory deployment. The fix in
`CircuitProtectorPolicy` benefits both backends. There is no SQLite backend in
the library.

## Design notes

- Point-in-time admission TOCTOU (a call in flight when another thread trips)
  is inherent and remains accepted, matching SPEC #2's out-of-scope note — the
  fix removes the *state-corruption* class of races (lost increments, buffer
  interleaving, duplicate `on_status_change`, success landing on a swapped
  OPEN object), not the in-flight-call window.
- `threading.RLock` keeps `on_status_change` re-entrancy safe with minimal
  restructuring; holding it only across refresh+validate and mark+save (never
  across the user callable) preserves call concurrency.
