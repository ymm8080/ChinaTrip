# -*- coding: utf-8 -*-
"""amap 双池复活 runner（2026-11-12，任务4 自动收尾，非调度器）。

背景：poi 批（v5 detail 池）与餐厅批（v5 around 池）双双熔断
（quota_exhausted_stop），配额重置时刻不明（0 点假设待验）。本 runner
每 10 分钟用 AmapClient 发 1 次 v5 place/detail 最小探测（真实 amap id，
拒绝调用不计费）——任一池复活即续跑对应 backfill；两池统计均干净
（无 quota_exhausted_stop）即退出；24h 硬上限。

运行：python -I _tmp_probe/amap_task4_runner.py
日志：devlogs/task4_backfill.log（追加）+ stdout 摘要。绝不打印 key。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")

CODES = Path(r"D:\CHINATRIP\CHINATRIP CODES")
LOG = CODES / "devlogs" / "task4_backfill.log"
INTERVAL = 600.0
COOLDOWN = 2400.0
HARD_CAP_H = 24.0


def now() -> str:
    return dt.datetime.now().strftime("%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"[runner {now()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _pick_amap_id() -> str | None:
    from sqlalchemy import select

    from app.db import get_session_factory
    from app.models import Poi

    sf = get_session_factory()
    with sf() as s:
        return s.scalar(
            select(Poi.source_poi_id)
            .where(Poi.status == "active", Poi.source == "amap")
            .limit(1)
        )


async def _probe_alive(amap_id: str) -> bool:
    from app.config import get_settings
    from app.services.amap_client import AmapClient

    st = get_settings()
    client = AmapClient(
        key=st.amap_api_key,
        base_url=st.amap_base_url,
        timeout_seconds=st.amap_timeout_seconds,
        route_timeout_seconds=st.amap_route_timeout_seconds,
    )
    try:
        await client.place_hours(amap_id)
        return True  # 有图无图都行——能 0 响应即池子活
    except Exception as e:  # noqa: BLE001
        kind = type(e).__name__
        log(f"probe dead: {kind}")
        return False


def _run_jobs() -> None:
    cmds = (
        [".venv/Scripts/python.exe", "-m", "app.jobs.backfill_photos",
         "--limit", "500"],
        [".venv/Scripts/python.exe", "-m", "app.jobs.backfill_restaurant_photos",
         "--limit", "500", "--concurrency", "2"],
    )
    for cmd in cmds:
        log("run: " + " ".join(cmd[3:]))
        with LOG.open("a", encoding="utf-8") as f:
            subprocess.run(cmd, cwd=CODES, stdout=f, stderr=f, check=False)


def _last_two_stats_clean() -> bool:
    """最后两条 backfill 统计都无熔断标记 = 两池都跑通。"""
    try:
        text = LOG.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    stats = [
        json.loads(m.group(0))
        for m in re.finditer(r"^\{.*\}$", text, re.MULTILINE)
        if '"targets"' in m.group(0)
    ]
    tail = stats[-2:]
    return len(tail) == 2 and all(
        s.get("stop") != "quota_exhausted_stop" for s in tail
    )


async def main() -> int:
    started = dt.datetime.now()
    amap_id = _pick_amap_id()
    if not amap_id:
        log("FATAL: no active amap-sourced poi id for probing")
        return 1
    log(f"runner start probe_id={amap_id[:8]}… interval={INTERVAL:.0f}s cap={HARD_CAP_H:.0f}h")
    while (dt.datetime.now() - started).total_seconds() < HARD_CAP_H * 3600:
        if _last_two_stats_clean():
            log("both pools done — exiting")
            return 0
        if await _probe_alive(amap_id):
            log("pool ALIVE — running task4 jobs")
            _run_jobs()
            if _last_two_stats_clean():
                log("both pools done — exiting")
                return 0
            log("melted again — cooldown before next probe")
            await asyncio.sleep(COOLDOWN)
        else:
            await asyncio.sleep(INTERVAL)
    log("hard cap reached — giving up")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
