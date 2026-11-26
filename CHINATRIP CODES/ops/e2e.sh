#!/usr/bin/env bash
# 真实 E2E 一键跑：真 Chromium + 真 uvicorn + 真求解器（LLM 是确定性桩）
#
#   bash ops/e2e.sh                     # 全部
#   bash ops/e2e.sh -k form_start       # 只跑某几条
#   E2E_HEADED=1 bash ops/e2e.sh        # 看着它点（排查用）
#   E2E_LLM=live bash ops/e2e.sh        # 用真模型（慢，别进日常回归）
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

# 浏览器装到仓库根，别写 C:\Users\...\ms-playwright（那台机器上装不进去）
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$(cd .. && pwd)/.pw-browsers}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

# 幂等：已装过 Chromium 会秒过
"$PY" -m playwright install chromium

exec "$PY" -m pytest tests/e2e -m e2e -v -p no:cacheprovider "$@"
