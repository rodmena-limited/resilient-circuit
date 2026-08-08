#!/usr/bin/env python3
"""Live probe for InMemoryStorage lifecycle gaps (ticket #3).

Pre-fix (0.5.0): InMemoryStorage grew without bound (no eviction, no cap) and
had no delete/reset API — dynamic resource keys pinned memory forever.

Scenarios:
  L1  entry cap          — with max_entries=N, writing >N distinct keys keeps
                           at most N; the oldest non-live entry is evicted.
  L2  live-OPEN pinned   — a live OPEN (unexpired open_until) is never
                           evicted, even past the cap (protection first).
  L3  expired evictable  — an OPEN whose open_until has expired is not live
                           and may be evicted (recovery semantics preserved).
  L4  delete_state       — delete_state removes the key and reports it; a
                           second delete reports False.

Expected pre-fix:  abort/FAIL (InMemoryStorage() has no max_entries kwarg;
delete_state does not exist) -> exit 1 (probe goes red)
Expected post-fix: all PASS -> exit 0

Run: python3 audit/evaluations/probe_inmemory_lifecycle.py
"""

import logging
import os
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

logging.disable(logging.CRITICAL)


def main():
    from resilient_circuit.storage import InMemoryStorage

    results = {}

    # --- L1: entry cap with oldest-non-live eviction ----------------------
    cap = 16
    storage = InMemoryStorage(max_entries=cap)
    for i in range(cap * 4):
        storage.set_state(f"k-{i}", "CLOSED", 0, 0)
    size = len(storage._states)
    oldest_gone = "k-0" not in storage._states
    newest_kept = f"k-{cap * 4 - 1}" in storage._states
    results["L1 entry cap + oldest-non-live eviction"] = (
        size <= cap and oldest_gone and newest_kept,
        f"wrote {cap * 4} keys; stored {size} (must be <= {cap}); "
        f"oldest evicted={oldest_gone}, newest kept={newest_kept}",
    )

    # --- L2: live OPEN is never evicted even past the cap -----------------
    storage = InMemoryStorage(max_entries=2)
    storage.set_state("a", "OPEN", 1, time.time() + 3600)
    storage.set_state("b", "OPEN", 1, time.time() + 3600)
    storage.set_state("c", "CLOSED", 0, 0)  # cap is 2 but a,b are live
    keys = set(storage._states.keys())
    results["L2 live-OPEN pinned past cap"] = (
        {"a", "b"} <= keys,
        f"stored {sorted(keys)} (must contain both live OPENs a and b)",
    )

    # --- L3: expired OPEN is evictable ------------------------------------
    storage = InMemoryStorage(max_entries=1)
    storage.set_state("old", "OPEN", 1, time.time() - 10)  # expired
    storage.set_state("new", "CLOSED", 0, 0)
    results["L3 expired OPEN is evictable"] = (
        "old" not in storage._states and "new" in storage._states,
        f"stored {list(storage._states.keys())} (must be ['new'] only)",
    )

    # --- L4: delete_state --------------------------------------------------
    storage = InMemoryStorage(max_entries=4)
    storage.set_state("gone", "OPEN", 1, time.time() + 3600)
    first = storage.delete_state("gone")
    second = storage.delete_state("gone")
    results["L4 delete_state removes and reports"] = (
        first is True and second is False and storage.get_state("gone") is None,
        f"first delete returned {first} (True), second {second} (False), "
        f"get after delete {storage.get_state('gone')} (None)",
    )

    failed = False
    for name, (ok, detail) in results.items():
        tag = "PASS" if ok else "FAIL"
        if not ok:
            failed = True
        print(f"  [{tag}] {name}\n         {detail}")
    print("probe result:", "RED (defect present)" if failed else "GREEN")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
