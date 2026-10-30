#!/usr/bin/env bash
# 双语描述回填常驻驱动 v2：无探针，直接跑作业本体。
#   Phase 1  pois 中文 intro；Phase 2  pois 英文 _en；Phase 3  restaurants 英文循环分批到清零。
# 续跑判据只看作业自身统计：filled>0 继续；errors==0 无目标/全 SKIP，收尾；
# errors>0 且 filled==0（429 等失败）睡 120s 直接重跑本批——作业被拒调用不计费。
# 严禁本脚本 kill 任何进程；所有作业只填空幂等。
set -u
cd "D:/CHINATRIP/CHINATRIP CODES"

filled_of() {
  echo "$1" | .venv/Scripts/python -c "
import json,sys
try:
    d = json.load(sys.stdin)
    print(d.get('rows_filled') or d.get('filled') or 0)
except Exception:
    print(0)
" 2>/dev/null
}

errors_of() {
  echo "$1" | .venv/Scripts/python -c "
import json,sys
try:
    print(json.load(sys.stdin).get('errors') or 0)
except Exception:
    print(0)
" 2>/dev/null
}

# run_stage <logfile> <args...>：循环直到 filled>0 且本批成功收尾，或 errors==0（无目标）
run_stage() {
  local logfile="$1"; shift
  while true; do
    .venv/Scripts/python "$@" > "$logfile" 2>&1
    local s; s=$(cat "$logfile")
    local f e; f=$(filled_of "$s"); e=$(errors_of "$s")
    echo "[$(date '+%F %T')] $* -> $s"
    if [ "$f" != "0" ]; then return 0; fi
    if [ "$e" = "0" ]; then return 0; fi
    sleep 120
  done
}

echo "[$(date '+%F %T')] === Phase 1: pois zh intro ==="
run_stage ops/backfill_intro_zh_round3.log -m app.jobs.backfill_intro_llm --limit 100 --concurrency 6

echo "[$(date '+%F %T')] === Phase 2: pois en columns (till one pass yields nothing) ==="
pass=0
while [ $pass -lt 5 ]; do
  pass=$((pass+1))
  run_stage ops/backfill_en_pois_round2.log -m app.jobs.backfill_en_columns --table pois --limit 5000 --concurrency 6
  # filled>0 说明这轮有产出，可能还有余量，再跑一轮；errors==0 表示已无目标
  f=$(filled_of "$(cat ops/backfill_en_pois_round2.log)")
  e=$(errors_of "$(cat ops/backfill_en_pois_round2.log)")
  [ "$f" = "0" ] && [ "$e" = "0" ] && break
done

echo "[$(date '+%F %T')] === Phase 3: restaurants en columns (till exhausted) ==="
while true; do
  run_stage ops/backfill_en_rest_round2.log -m app.jobs.backfill_en_columns --table restaurants --limit 1500 --concurrency 6
  f=$(filled_of "$(cat ops/backfill_en_rest_round2.log)")
  e=$(errors_of "$(cat ops/backfill_en_rest_round2.log)")
  [ "$f" = "0" ] && [ "$e" = "0" ] && { echo "[$(date '+%F %T')] restaurants exhausted"; break; }
done

echo "[$(date '+%F %T')] === final counts ==="
.venv/Scripts/python -c "
from app.db import get_session_factory
from sqlalchemy import text
s = get_session_factory()()
print('pois active zh intro missing:', s.execute(text(\"SELECT COUNT(*) FROM pois WHERE status='active' AND (intro IS NULL OR intro='')\")).one()[0])
print('pois intro_en missing:', s.execute(text(\"SELECT COUNT(*) FROM pois WHERE (intro_en IS NULL OR intro_en='') AND intro IS NOT NULL AND intro<>''\")).one()[0])
print('restaurants name_en missing:', s.execute(text(\"SELECT COUNT(*) FROM restaurants WHERE (name_en IS NULL OR name_en='') AND name_zh IS NOT NULL AND name_zh<>''\")).one()[0])
print('restaurants intro_en missing:', s.execute(text(\"SELECT COUNT(*) FROM restaurants WHERE (intro_en IS NULL OR intro_en='') AND intro IS NOT NULL AND intro<>''\")).one()[0])
"
echo "[$(date '+%F %T')] driver complete"
