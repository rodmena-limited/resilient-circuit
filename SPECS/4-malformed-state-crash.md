# Ticket #4 — Protected call crashes on malformed stored state

Origin: full-library resiliency evaluation (Sisyphus, 2026-08-08). Live probe:
with `state='SOMETHING_ELSE'` stored, a guarded call raises
`ValueError: 'SOMETHING_ELSE' is not a valid CircuitStatus`; with
`open_until='not-a-number'`, it raises `ValueError: could not convert string to float`.

Root cause: `_load_state` guards `storage.get_state()` but not the subsequent
`_apply_stored`; `_refresh_before_admission` guards neither `get_state` (it does)
nor `_adopt_stored`/`_apply_stored`. `CircuitStatus(state_data["state"])` and
`float(state_data.get("open_until", 0))` raise inside `__call__`, so one corrupt
row breaks every protected call on that key. Postgres rows are user-editable
(README documents direct SQL), so corrupt/legacy rows are plausible.

## Scope confirmation (post-evaluation, pre-fix)

**NOT in-memory-only.** Reproduced live against a real Postgres row
(`state='SOMETHING_ELSE'` in namespace `probe-m4pg-*`): the guarded call raised
`ValueError: 'SOMETHING_ELSE' is not a valid CircuitStatus`. The crash lives in
the policy layer (`_apply_stored`/`_adopt_stored`), backend-agnostic — the fix
in `CircuitProtectorPolicy` covers both `InMemoryStorage` and `PostgresStorage`.
There is no SQLite backend in the library.

## EARS SPEC (system: CircuitProtectorPolicy)

- If the stored state for a resource key is malformed (unknown state value,
  non-numeric `failure_count` or `open_until`), then the `CircuitProtectorPolicy`
  shall not raise from state load or adoption; it shall log the malformed state,
  ignore it, and fall back to the default CLOSED state.
- While a malformed stored state is present, the `CircuitProtectorPolicy` shall
  self-heal by overwriting the malformed row on the next successful write.
- The malformed-state handling shall apply identically in `_load_state` and the
  pre-admission refresh path (`_adopt_stored`).

## Regression constraints

- Must not change behavior for well-formed states (all 119 existing tests green).
- The fallback-to-CLOSED path already exists in `_load_state`'s `except`; the fix
  extends the same discipline to the refresh/adoption path and to malformed
  *content* (not just storage I/O errors).
