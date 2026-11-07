# -*- coding: utf-8 -*-
"""POI 补全会话环·单轮执行器（2026-11-06 用户指令：本会话每 2 分钟反应）。

后台 sleep 120 退出叫醒会话 → 跑本脚本一轮 → 重新挂 sleep。状态落
ops/pois_fill_loop_state.json（计数/连零游程/tick 数），日志追加
ops/pois_fill_loop_20261106.log。停止条件（脚本输出 STOP reasons，
由会话侧决定不再续挂）：
  * 全部终点（name_en/可翻译addr_en/intro=0 且 category=0 或 abstain
    枯竭 3 轮）连续 2 轮 → DONE
  * 零产出游程 ≥5 → STALL（外部配额卡死等）
  * tick ≥360（12h 保险丝）

每轮只跑一个写作业（优先级：addr > category > tail > intro >
heuristics），全部只填空幂等；GLM 429 当轮记 skip 不重试。
坐标 8 行死角归 ChinaTrip\\coords nightly，不在本环。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STATE_FILE = ROOT / "ops" / "pois_fill_loop_state.json"
LOG_FILE = ROOT / "ops" / "pois_fill_loop_20261106.log"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")

JOBS = {
    "addr": ["ops/backfill_poi_en.py", "addr", "--batch", "20", "--limit", "500"],
    "category": ["ops/backfill_category_llm.py", "--limit", "100", "--batch", "20"],
    "tail": ["ops/backfill_poi_en.py", "tail", "--batch", "25", "--limit", "300"],
    "intro": [
        "-m", "app.jobs.backfill_intro_llm", "--limit", "300", "--concurrency", "4"
    ],
    "heuristics": [
        "-m", "app.jobs.enrich_heuristics", "--limit", "5000", "--with-duration"
    ],
}


def read_counters() -> dict:
    import psycopg

    conn = psycopg.connect(
        "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip",
        connect_timeout=10,
    )
    cur = conn.cursor()
    out: dict[str, int] = {}
    cur.execute("select count(*) from pois")
    out["total"] = cur.fetchone()[0]
    cur.execute("select count(*) from pois where status='active'")
    active = cur.fetchone()[0]
    out["active"] = active
    for col in ("category", "name_en", "intro"):
        cur.execute(
            f"select count(*) from pois where status='active' and {col} is null"
        )
        out[col] = cur.fetchone()[0]
    cur.execute(
        "select count(*) from pois where status='active' "
        "and address is not null and address_en is null"
    )
    out["addr_en"] = cur.fetchone()[0]
    cur.execute(
        "select count(*) from pois where status='active' and location is null"
    )
    out["location"] = cur.fetchone()[0]
    conn.close()
    return out


def pick_job(counters: dict, state: dict) -> str | None:
    if counters["addr_en"] > 0:
        return "addr"
    if counters["category"] > 0 and state.get("abstain_streak", 0) < 3:
        return "category"
    if counters["name_en"] > 0:
        return "tail"
    if counters["intro"] > 0:
        return "intro"
    return None


def main() -> int:
    state: dict = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    tick = int(state.get("tick", 0)) + 1
    prev = state.get("counters", {})
    counters = read_counters()
    note = ""

    job = pick_job(counters, state)
    if job:
        subprocess.run(
            [PY, *JOBS[job]], cwd=str(ROOT), capture_output=True, text=True,
            timeout=880,
        )
        after = read_counters()
        if after.get(job if job != "addr" else "addr_en", 0) >= counters.get(
            job if job != "addr" else "addr_en", 0
        ) and after["total"] == counters["total"]:
            note = f"{job}: no progress this round"
        counters = after
    elif counters["total"] != prev.get("total"):
        job = "heuristics"
        subprocess.run([PY, *JOBS[job]], cwd=str(ROOT), capture_output=True,
                       text=True, timeout=880)
        counters = read_counters()

    # 游程统计
    zero_progress = note.startswith(job or "x") if job else True
    if job and not zero_progress:
        state["zero_streak"] = 0
    else:
        state["zero_streak"] = int(state.get("zero_streak", 0)) + 1
    if job == "category" and zero_progress:
        state["abstain_streak"] = int(state.get("abstain_streak", 0)) + 1
    elif job != "category":
        pass
    state.update(tick=tick, counters=counters, last_job=job, last_note=note)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                          encoding="utf-8")

    done = (
        counters["name_en"] == 0
        and counters["addr_en"] == 0
        and counters["intro"] == 0
        and (counters["category"] == 0
             or int(state.get("abstain_streak", 0)) >= 3)
    )
    reasons = []
    if done and int(state.get("done_streak", 0)) >= 1:
        reasons.append("DONE")
    elif done:
        state["done_streak"] = int(state.get("done_streak", 0)) + 1
    if int(state.get("zero_streak", 0)) >= 5:
        reasons.append("STALL")
    if tick >= 360:
        reasons.append("FUSE")
    state["done_streak"] = int(state.get("done_streak", 0))
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                          encoding="utf-8")

    line = (
        f"[{datetime.now().isoformat(timespec='seconds')}] tick={tick} "
        f"job={job} {note} | total={counters['total']} "
        f"cat={counters['category']} name_en={counters['name_en']} "
        f"intro={counters['intro']} addr_en={counters['addr_en']} "
        f"loc={counters['location']} zero_streak={state.get('zero_streak', 0)}"
    )
    LOG_FILE.open("a", encoding="utf-8").write(line + "\n")
    print(line)
    print("STOP:" + (",".join(reasons) if reasons else "no"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
