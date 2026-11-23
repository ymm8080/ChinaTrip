#!/bin/sh
# Pre-push test gate (2026-11-23, anti-regression rule #2).
# Full pytest suite must be green before any push. Installed as
# .git/hooks/pre-push; run standalone anytime: sh ops/prepush_gate.sh
# Override a specific push with: git push --no-verify (use sparingly,
# and fix the red test right after - never leave the gate red).
cd "$(git rev-parse --show-toplevel)/CHINATRIP CODES" || exit 1

PY=".venv/Scripts/python.exe"
[ -f "$PY" ] || PY=python

echo "[pre-push gate] running full test suite (e2e excluded)..."
# NOTE: do NOT add -p no:logging here - it kills the logging plugin and
# with it the built-in caplog fixture (9 spurious ERRORs, 2026-11-23).
"$PY" -m pytest tests -q
rc=$?

if [ $rc -ne 0 ]; then
    echo "" >&2
    echo "[pre-push gate] RED: tests failed (exit $rc). PUSH BLOCKED." >&2
    echo "[pre-push gate] Fix the failing test first, then push again." >&2
    echo "[pre-push gate] Emergency bypass: git push --no-verify (fix immediately after)." >&2
else
    echo "[pre-push gate] GREEN: suite passed, push allowed."
fi
exit $rc
