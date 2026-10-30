"""坐标补全自动轮驱动（ops）：选行 → 剔除已 miss 行 → 整批回填 → 记录 miss。

在 app.jobs.backfill_locations 之上的续跑包装：
- miss 台账 ops/backfill_coords_missed.txt（每行 `source_poi_id 原因`），
  台账内行不再重试（检索/geocode 查询确定性，重试只烧配额）；渠道恢复
  （次日配额重置）后可清台账整体重试一轮。
- 整批一次 backfill_rows（保留 vendor dead-latch）；批次因 stopped_no_channel
  提前停时不记 miss（未尝试行下轮重试）；其余批次后仍无坐标的行按
  「geocode 未命中/不近城心 且 检索无命中」记 miss。
- 用法：python ops/backfill_coords_driver.py [--limit 100]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MISS_FILE = Path(__file__).resolve().parent / "backfill_coords_missed.txt"


def _load_missed() -> dict[str, str]:
    if not MISS_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in MISS_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if parts:
            out[parts[0]] = parts[1] if len(parts) > 1 else ""
    return out


def _append_missed(new: dict[str, str]) -> None:
    if not new:
        return
    with MISS_FILE.open("a", encoding="utf-8") as fh:
        for pid, reason in sorted(new.items()):
            fh.write(f"{pid} {reason}\n".rstrip() + "\n")


def select_outside_pool_rows(limit: int) -> list:
    """池外行：active + 非餐饮 + 无坐标 + 有 city，但不落在 KNOWN_CITIES
    规划池（长尾小城/show 行的括号城市格式）。作业主流程按设计跳过它们，
    这里单列补齐（仅数据完整性，不影响规划池口径）。"""
    from sqlalchemy import or_

    from app.db import get_session_factory
    from app.jobs.backfill_locations import _FOOD_MARKS
    from app.models import Poi
    from app.services.agent.plan import KNOWN_CITIES

    cities: list[str] = []
    for c in KNOWN_CITIES:
        cities += [c, f"{c}市"]
    with get_session_factory()() as session:
        q = session.query(Poi).filter(
            Poi.location.is_(None),
            or_(Poi.status.is_(None), Poi.status == "active"),
            Poi.city.isnot(None),
            Poi.city != "",
            ~Poi.city.in_(cities),
        )
        for mark in _FOOD_MARKS:
            q = q.filter(or_(Poi.category.is_(None), ~Poi.category.ilike(f"%{mark}%")))
        rows = q.all()
    return rows[:limit]


async def run(limit: int, *, extras: bool = False) -> dict:
    from sqlalchemy import or_

    from app.config import get_settings
    from app.db import get_session_factory
    from app.jobs.backfill_locations import backfill_rows, select_rows
    from app.models import Poi
    from app.services.map_provider import build_client_chain, build_vendor
    from app.services.poi_details import PoiDetailStore

    missed = _load_missed()
    if extras:
        rows = select_outside_pool_rows(10_000)
    else:
        rows = select_rows(10_000)
    rows = [r for r in rows if r.source_poi_id not in missed][:limit]
    ids = [r.source_poi_id for r in rows]
    settings = get_settings()
    clients = build_client_chain(settings, "search")
    geocoder = build_vendor("baidu", settings)
    store = PoiDetailStore(session_factory=get_session_factory())
    stats = await backfill_rows(store, clients, rows, geocoder=geocoder)

    if not stats.get("stopped_no_channel") and ids:
        with get_session_factory()() as session:
            still_open = {
                pid
                for (pid,) in session.query(Poi.source_poi_id)
                .filter(
                    Poi.source_poi_id.in_(ids),
                    or_(Poi.location.is_(None)),
                )
                .all()
            }
        _append_missed(
            {pid: "geocode+search 未命中（2026-10-30 批）" for pid in still_open}
        )
        stats["new_missed"] = len(still_open)
    stats["skipped_miss_file"] = len(missed)
    stats["selected"] = len(rows)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--extras",
        action="store_true",
        help="补池外行（KNOWN_CITIES 之外的长尾/show 行）而非规划池行",
    )
    args = parser.parse_args()
    stats = asyncio.run(run(args.limit, extras=args.extras))
    print(stats)


if __name__ == "__main__":
    main()
