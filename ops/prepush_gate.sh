#!/bin/sh
# Pre-push test gate (2026-11-23, anti-regression rule #2; hardened R24).
# Full pytest suite must be green before any push. Installed as
# .git/hooks/pre-push; run standalone anytime: sh ops/prepush_gate.sh
# Override a specific push with: git push --no-verify (use sparingly,
# and fix the red test right after - never leave the gate red).
#
# 2026-11-23 hardening (R24, exit-127 false gate):
#   * python resolution: current worktree venv -> main-worktree venv (hooks
#     also run from linked worktrees, where .venv is absent and PATH python
#     can be the Store stub) -> PATH python/python3; every candidate must
#     import pytest before use.
#   * keep the interpreter test on a separate line from "cd" (a failed cd
#     must not look like a missing interpreter).
#   * -p no:cacheprovider: concurrent gates (parallel sessions push every few
#     minutes) no longer fight over .pytest_cache.
#   * infrastructure failure (no usable interpreter, rc=3 internal error,
#     rc=4 usage error, rc=127 exec failure) prints GATE UNAVAILABLE and lets
#     the push through; real test failures (rc=1) still block.
#   * PREPUSH_GATE_TESTS env can narrow the target for a quick self-test
#     (default: tests).
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
    echo "" >&2
    echo "[pre-push gate] GATE UNAVAILABLE: no python with pytest found" >&2
    echo "[pre-push gate]   tried: .venv/Scripts/python.exe, $MAIN_PY, python, python3" >&2
    echo "[pre-push gate] allowing push (environment problem, not a test result)." >&2
    exit 0
fi

TESTS=${PREPUSH_GATE_TESTS:-tests}
echo "[pre-push gate] running full test suite (e2e excluded)... [$PY]"
"$PY" -m pytest "$TESTS" -q -p no:cacheprovider
rc=$?

case $rc in
    0)
        echo "[pre-push gate] GREEN: suite passed, push allowed."
        exit 0
        ;;
    3|4|127)
        echo "" >&2
        echo "[pre-push gate] GATE UNAVAILABLE: pytest could not run properly (exit $rc)." >&2
        echo "[pre-push gate] allowing push; fix the gate environment right after." >&2
        exit 0
        ;;
    *)
        echo "" >&2
        echo "[pre-push gate] RED: tests failed (exit $rc). PUSH BLOCKED." >&2
        echo "[pre-push gate] Fix the failing test first, then push again." >&2
        echo "[pre-push gate] Emergency bypass: git push --no-verify (fix immediately after)." >&2
        exit "$rc"
        ;;
esac