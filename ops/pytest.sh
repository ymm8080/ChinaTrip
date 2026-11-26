#!/bin/sh
# Concurrent-safe pytest runner (2026-11-26 R50).
#
# WHY: this worktree routinely has more than one pytest alive at a time — the
# pre-push gate, an agent session's verification run, and a parallel session's
# run. pytest numbers per-test temp dirs IDENTICALLY in every process, so any
# two runs that share a --basetemp share the exact same tmp_path trees and
# corrupt each other's fixtures. On 2026-11-25 that showed up as
# "1 failed ... 156 errors" in the gate (test_travelers_api / test_trip_items
# row-count asserts seeing another run's rows); both files were green solo.
# Reproduced in isolation: shared basetemp => one run errors; unique basetemps
# => both runs pass, twice over.
#
# RULES this wrapper enforces:
#   * --basetemp is unique per process ("run.$$") and repo-local (never the
#     system temp root, whose pytest GC trips the sandbox bulk-delete guard);
#   * -p no:cacheprovider, so concurrent runs never write .pytest_cache;
#   * stale run trees are pruned to the newest 3 at start, best-effort, never
#     at exit (a teardown-time bulk delete is what broke a green run once).
#
# USAGE: sh ops/pytest.sh                          # whole suite
#        sh ops/pytest.sh tests/test_plan_api.py -k foo
#        sh ops/pytest.sh -x --lf
# Do NOT hand-roll `pytest --basetemp=.pytest_tmp/<fixed>` anywhere: that is
# exactly the collision this script exists to prevent.
TOPLEVEL=$(git rev-parse --show-toplevel) || exit 1
CODE_DIR="$TOPLEVEL/CHINATRIP CODES"
[ -d "$CODE_DIR" ] || CODE_DIR="$TOPLEVEL"
cd "$CODE_DIR" || exit 1

MAIN_GIT=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
MAIN_ROOT=${MAIN_GIT%/.git}
MAIN_PY="$MAIN_ROOT/CHINATRIP CODES/.venv/Scripts/python.exe"

try_py() {
    _p=$1
    [ -n "$_p" ] || return 1
    case "$_p" in
        */*) [ -f "$_p" ] || return 1 ;;
    esac
    "$_p" -c "import pytest" >/dev/null 2>&1 || return 1
    printf '%s' "$_p"
}

PY=""
for cand in ".venv/Scripts/python.exe" "$MAIN_PY" python python3; do
    PY=$(try_py "$cand") && break
    PY=""
done
if [ -z "$PY" ]; then
    echo "[pytest.sh] no python with pytest found" >&2
    exit 127
fi

BASE="$CODE_DIR/.pytest_tmp"
mkdir -p "$BASE" 2>/dev/null || true
for _old in $(ls -1dt "$BASE"/run.* 2>/dev/null | tail -n +4); do
    rm -rf "$_old" 2>/dev/null || true
done

exec "$PY" -m pytest -q -p no:cacheprovider --basetemp="$BASE/run.$$" "$@"
