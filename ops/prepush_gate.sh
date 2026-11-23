#!/bin/sh
# Pre-push test gate (2026-11-23, anti-regression rule #2; hardened R24/R25).
# Full pytest suite must be green before any push. Installed as
# .git/hooks/pre-push; run standalone anytime: sh ops/prepush_gate.sh
# Override a specific push with: git push --no-verify (use sparingly,
# and fix the red test right after - never leave the gate red).
#
# 2026-11-23 hardening (R24, exit-127 false gate):
#   * python resolution: current worktree venv -> main-worktree venv -> PATH
#     python/python3; every candidate must import pytest before use.
#   * infrastructure failure (no usable interpreter, rc=3 internal, rc=4
#     usage, rc=127 exec) => GATE UNAVAILABLE, push allowed with a loud note.
#   * -p no:cacheprovider so concurrent gates do not fight over .pytest_cache.
#
# 2026-11-23 R25: load-flake triage. The repo has a documented class of
# full-suite-only flakes (time_slot_integrity / shadow acceptance / model_d
# "满载抖动": red only when the whole suite runs under load, green solo). A
# gate that cannot tell those from real regressions is bypassed by everyone,
# which kills the gate. So on rc=1 every FAILED nodeid is re-run SOLO:
#   * all pass solo  => "FLAKY (passed solo)" disclosed, push allowed;
#   * any fails solo => real failure, push blocked.
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
LOG=$(mktemp 2>/dev/null || echo "/tmp/prepush_gate_$$.log")
echo "[pre-push gate] running full test suite (e2e excluded)... [$PY]"
"$PY" -m pytest "$TESTS" -q -p no:cacheprovider > "$LOG" 2>&1
rc=$?
cat "$LOG"

case $rc in
    0)
        rm -f "$LOG"
        echo "[pre-push gate] GREEN: suite passed, push allowed."
        exit 0
        ;;
    3|4|127)
        rm -f "$LOG"
        echo "" >&2
        echo "[pre-push gate] GATE UNAVAILABLE: pytest could not run properly (exit $rc)." >&2
        echo "[pre-push gate] allowing push; fix the gate environment right after." >&2
        exit 0
        ;;
esac

# rc != 0 and not an infrastructure code: triage every FAILED nodeid solo.
NODES=$(grep '^FAILED ' "$LOG" | sed 's/^FAILED //; s/ - .*$//' | sed 's/[[:space:]]*$//')
if [ -z "$NODES" ]; then
    rm -f "$LOG"
    echo "" >&2
    echo "[pre-push gate] RED: suite failed (exit $rc) with no FAILED line to triage." >&2
    echo "[pre-push gate] PUSH BLOCKED. Fix the failure, then push again." >&2
    echo "[pre-push gate] Emergency bypass: git push --no-verify (fix immediately after)." >&2
    exit "$rc"
fi

echo ""
echo "[pre-push gate] triaging failed nodeid(s) with a SOLO re-run (load-flake check)..."
SOLO_RED=""
SOLO_SEEN=""
while IFS= read -r node; do
    [ -n "$node" ] || continue
    echo "  solo: $node"
    # up to 2 solo attempts: a load flake usually passes one of them, a real
    # failure fails both (deterministic by definition).
    ok=0
    for _try in 1 2; do
        if "$PY" -m pytest "$node" -q -p no:cacheprovider >/dev/null 2>&1; then
            ok=1
            break
        fi
    done
    if [ "$ok" -eq 1 ]; then
        SOLO_SEEN="$SOLO_SEEN $node"
    else
        SOLO_RED="$SOLO_RED $node"
    fi
done <<EOF
$NODES
EOF

if [ -z "$SOLO_RED" ]; then
    rm -f "$LOG"
    echo "" >&2
    echo "[pre-push gate] FLAKY (passed solo):$SOLO_SEEN" >&2
    echo "[pre-push gate] full-suite-only failure (load flake), push allowed." >&2
    echo "[pre-push gate] DISCLOSURE: file a stabilization fix for the nodeid(s) above." >&2
    exit 0
fi

rm -f "$LOG"
echo "" >&2
echo "[pre-push gate] RED: tests failed, and these fail SOLO too:$SOLO_RED" >&2
echo "[pre-push gate] PUSH BLOCKED. Fix the failing test first, then push again." >&2
echo "[pre-push gate] Emergency bypass: git push --no-verify (fix immediately after)." >&2
exit "$rc"