# -*- coding: utf-8 -*-
"""数据回填调度节拍循环（2026-11-11，用户指令「SET SCHEDULER EVERY 2 MINUTES TILL TASKS ARE COMPLETE」）。

每 ~120s 一轮：
  1. 进程闸：有 enrich_ctrip_detail / enrich_baidu_map 在飞则本轮只观察；
  2. 携程收割：enrich_ctrip_detail --limit 600 --concurrency 2（前台同步，通道活则填 curated 优先组 ticket/rating）；
  3. 缺口核查：active 口径 curated ticket/rating 缺口；
  4. 完成判据：双缺口=0 或通道连续 5 轮零产出 → 写台账、退出；
  5. 简报逐行追加 ops/scheduler_1111.log（>500 行截尾 200）。
上限 8 小时保险丝。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(r"D:\CHINATRIP\CHINATRIP CODES")
sys.path.insert(0, str(REPO))
LOG = REPO / "ops" / "scheduler_1111.log"
ROUND_SECONDS = 120
MAX_ROUNDS = 240
EXHAUST_LIMIT = 5


def log(line: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%m-%d %H:%M:%S} {line}\n")
    if LOG.exists() and sum(1 for _ in LOG.open(encoding="utf-8")) > 500:
        lines = LOG.read_text(encoding="utf-8").splitlines()
        LOG.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")


def procs_running() -> list[str]:
    """tasklist 查在飞回填进程（按命令行匹配，PowerShell CIM）。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -match 'enrich_(ctrip_detail|baidu_map|amap_detail)' } | "
          "Select-Object -ExpandProperty CommandLine")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=60)
    return [ln for ln in (r.stdout or "").splitlines() if ln.strip()]


def run_ctrip() -> dict:
    code = ("import sys; sys.path.insert(0, r'D:\\CHINATRIP\\CHINATRIP CODES'); "
            "from app.jobs.enrich_ctrip_detail import main; "
            "sys.argv = ['enrich_ctrip_detail', '--limit', '600', '--concurrency', '2']; main()")
    r = subprocess.run([str(REPO / ".venv" / "Scripts" / "python.exe"), "-I", "-c", code],
                       capture_output=True, text=True, timeout=1800, cwd=str(REPO))
    out = (r.stdout or "").strip().splitlines()
    for ln in reversed(out):
        try:
            return json.loads(ln)
        except Exception:  # noqa: PERF203 — 尾行非 JSON 则继续
            continue
    return {"error": (r.stderr or r.stdout or "no json")[-200:]}


def gaps() -> tuple[int, int]:
    from sqlalchemy import func, select
    from app.db import get_session_factory
    from app.models import Poi
    sf = get_session_factory()
    with sf() as s:
        t = s.scalar(select(func.count()).select_from(Poi).where(
            Poi.source == "curated", Poi.status == "active", Poi.ticket_price_min.is_(None)))
        r = s.scalar(select(func.count()).select_from(Poi).where(
            Poi.source == "curated", Poi.status == "active", Poi.rating.is_(None)))
    return int(t or 0), int(r or 0)


def append_ledger(stats: str) -> None:
    from datetime import date
    entry = (f"- {date.today():%Y-%m-%d} 调度节拍轮收口（每2分钟直至完成）：{stats}。"
             f"明细见 ops/scheduler_1111.log。\n")
    p = REPO / "ops" / "p1_data_tasks_progress.md"
    with p.open("a", encoding="utf-8") as f:
        f.write(entry)


def main() -> int:
    log("scheduler loop START (2min cadence, fuse 240 rounds)")
    exhausted = 0
    last = (0, 0)
    for rnd in range(1, MAX_ROUNDS + 1):
        attempted = False
        try:
            running = procs_running()
            if running:
                log(f"R{rnd} gate: parallel enrich process in flight, observe only ({len(running)})")
            else:
                st = run_ctrip()
                attempted = True
                log(f"R{rnd} ctrip: {json.dumps(st, ensure_ascii=True)[:300]}")
        except Exception as e:  # noqa: BLE001 — 单轮异常不掀翻循环
            log(f"R{rnd} EXC {type(e).__name__}: {e}")
        cur = gaps()
        log(f"R{rnd} gaps: ticket={cur[0]} rating={cur[1]}")
        if cur == (0, 0):
            append_ledger(f"curated ticket/rating 双缺口归零（ticket={cur[0]}, rating={cur[1]}）")
            log("DONE: gaps zeroed, ledger written, exiting")
            return 0
        # 仅对「真正尝试过收割」且缺口纹丝不动的轮次计耗尽；闸口观察轮不计
        if cur == last and attempted:
            exhausted += 1
        else:
            exhausted = 0
        if exhausted >= EXHAUST_LIMIT:
            append_ledger(f"双通道连续 {EXHAUST_LIMIT} 个收割轮零产出判定耗尽（ticket={cur[0]}, rating={cur[1]}）")
            log(f"DONE: channels exhausted {EXHAUST_LIMIT} harvest rounds, ledger written, exiting")
            return 0
        last = cur
        time.sleep(ROUND_SECONDS)
    log("FUSE: max rounds reached, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
