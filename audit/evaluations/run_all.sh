#!/usr/bin/env bash
# Run the safe live-probe harness for resilient-circuit.
#
# Every probe drives the library through its public API against a real
# PostgreSQL instance and prints PASS/FAIL plus the evidence it observed.
# Exits non-zero if any probe goes red.
#
# Target is parameterised -- no hardcoded credentials, no baked-in endpoint:
#   RC_PROBE_DSN   libpq DSN for the probe database
#                  (default: "dbname=resilient_circuit_test")
#
# The probes create and drop their own namespaces; they are safe against a
# database you do not mind them writing test rows into. Point RC_PROBE_DSN at
# a scratch database, never at production.

set -uo pipefail

cd "$(dirname "$0")/../.." || exit 2

export RC_PROBE_DSN="${RC_PROBE_DSN:-dbname=resilient_circuit_test}"
PYTHON="${PYTHON:-python3}"

echo "resilient-circuit probe harness"
echo "  DSN: ${RC_PROBE_DSN}"
echo

failed=()
passed=()
skipped=()

# Probe exit-code contract: 0 = green, 1 = red (defect reproduced),
# 2 = skipped (destructive probe without AUDIT_ALLOW_DESTRUCTIVE=1, or a
# missing prerequisite). A skip is not a pass and not a failure.
for probe in audit/evaluations/probe_*.py; do
    name="$(basename "$probe")"
    echo "─── ${name} ───────────────────────────────────────────"
    "$PYTHON" "$probe"
    rc=$?
    case "$rc" in
        0) passed+=("$name") ;;
        2) skipped+=("$name") ;;
        *) failed+=("$name") ;;
    esac
    echo
done

echo "══════════════════════════════════════════════════════════"
echo "PASSED (${#passed[@]}):"
for p in "${passed[@]:-}"; do [ -n "$p" ] && echo "  green  $p"; done
echo "SKIPPED (${#skipped[@]}):"
for s in "${skipped[@]:-}"; do [ -n "$s" ] && echo "  skip   $s (opt-in required)"; done
echo "FAILED (${#failed[@]}):"
for f in "${failed[@]:-}"; do [ -n "$f" ] && echo "  RED    $f"; done

if [ "${#failed[@]}" -gt 0 ]; then
    echo
    echo "harness result: RED — ${#failed[@]} probe(s) reproduced a defect"
    exit 1
fi

echo
echo "harness result: GREEN — all probes passed"
