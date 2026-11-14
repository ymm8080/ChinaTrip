"""POI 照片批量预热作业（DESIGN poi_photos_functional_design 2026-11-11 §3-F2）.

覆盖率现状：active 9,787 行仅 1,650 有图（16.9%），restaurants 为 0。
本 job 走与点击回源同一条 fetch_photo_chain 链（amap v5 id → amap v3
按名搜 → wikimedia P18），把有图率先抬一档；点击端点兜长尾。

选行：status='active' 且 photos 为空，且 24h 内未尝试过回源（
photos_fetched_at 冷却同端点口径——拉空行 24h 内不重烧）。排序走
source_tier.SOURCE_PRIORITY 全链（CLAUDE.md Iron rule 唯一定义点，
import 不抄短表），再 rating 降序。城市过滤 --city（contains 宽匹配，
库内存「重庆市」/「重庆」两种形状）。

写库：逐列只填空——photos 为空且链上拉到才写 photos/photos_source；
photos_fetched_at 尝试即落戳（失败也落），与点击端点一致。

配额：amap USER_DAILY_QUERY_OVER_LIMIT 首撞即停整轮（熔断语义，
fetch_photo_chain 对 AmapQuotaExhaustedError 原样上抛），明日重置续跑；
fill-empty-only + 24h 冷却保证无损续跑。

无 amap key 也可跑（链自动只剩 wikimedia 一档，amap=None）。

用法：
    python -m app.jobs.backfill_photos [--limit 500] [--city 重庆]
                                       [--concurrency 3] [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import case, or_

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.amap_client import AmapClient, AmapQuotaExhaustedError
from app.services.poi_photos import fetch_photo_chain
from app.services.source_tier import SOURCE_PRIORITY

_DEFAULT_LIMIT = 500
_DEFAULT_CONCURRENCY = 3
_QUOTA_STOP = "quota_exhausted_stop"

# 唯一定义点 app.services.source_tier.SOURCE_PRIORITY（CLAUDE.md Iron rule），
# 只 import 排序用，不复制缩短版。
_SOURCE_PRIORITY = SOURCE_PRIORITY


def select_targets(
    session_factory, *, limit: int, city: str | None = None
) -> list[Poi]:
    cooldown_deadline = datetime.now() - timedelta(hours=24)
    source_rank = case(
        *[(Poi.source == src, rank) for rank, src in enumerate(_SOURCE_PRIORITY)],
        else_=len(_SOURCE_PRIORITY),
    )
    with session_factory() as session:
        q = (
            session.query(Poi)
            .filter(
                Poi.status == "active",
                Poi.photos.is_(None),
                or_(
                    Poi.photos_fetched_at.is_(None),
                    Poi.photos_fetched_at < cooldown_deadline,
                ),
            )
            .order_by(source_rank, Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
        )
        if city:
            q = q.filter(Poi.city.contains(city))
        return q.all()


class _Target(NamedTuple):
    poi_id: object
    name_zh: str
    city: str | None
    source: str | None
    source_poi_id: str | None


def _write_row(factory, poi_id, photos, source) -> list[str]:
    """逐列只填空写库；返回实际写入的列名清单。"""
    written: list[str] = []
    now = datetime.now()
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return written
        row.photos_fetched_at = now  # 尝试即落戳（与点击端点同口径）
        if photos and row.photos is None:
            row.photos = photos
            row.photos_source = source
            written += ["photos", "photos_source"]
        session.commit()
    return written


async def _process_row(
    amap, factory, t: _Target, sem: asyncio.Semaphore, stats: dict
) -> None:
    async with sem:
        try:
            photos, source = await fetch_photo_chain(t, amap=amap)
        except AmapQuotaExhaustedError:
            stats["stop"] = _QUOTA_STOP  # 首撞即停，明日重置再跑
            return
        except Exception:
            stats["errors"] += 1
            return
    if not photos:
        stats["no_data"] += 1
        # 拉空也落冷却戳，防下轮重烧——复用 _write_row 落戳逻辑
        await asyncio.to_thread(_write_row, factory, t.poi_id, None, None)
        return
    stats["hits"] += 1
    written = await asyncio.to_thread(_write_row, factory, t.poi_id, photos, source)
    for col in written:
        stats["filled"][col] = stats["filled"].get(col, 0) + 1


async def backfill(
    factory, settings, *, limit, city, concurrency, no_amap=False
) -> dict:
    stats: dict = {
        "targets": 0,
        "hits": 0,
        "no_data": 0,
        "errors": 0,
        "filled": {},
        "stop": None,
    }
    rows = select_targets(factory, limit=limit, city=city)
    stats["targets"] = len(rows)
    targets = [
        _Target(
            r.id,
            (r.name_zh or "").strip(),
            r.city,
            r.source,
            r.source_poi_id if r.source == "amap" else None,
        )
        for r in rows
    ]
    amap = (
        AmapClient(key=settings.amap_api_key, timeout_seconds=10.0)
        if settings.amap_api_key and not no_amap
        else None
    )
    sem = asyncio.Semaphore(max(1, concurrency))
    await asyncio.gather(*(_process_row(amap, factory, t, sem, stats) for t in targets))
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int, city: str | None) -> None:
    rows = select_targets(session_factory, limit=limit, city=city)
    by_source: dict[str | None, int] = {}
    for r in rows:
        by_source[r.source] = by_source.get(r.source, 0) + 1
    print(
        json.dumps(
            {"dry_run": True, "targets": len(rows), "by_source": by_source},
            ensure_ascii=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="POI photos batch backfill (deterministic chain)"
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--city", type=str, default=None)
    parser.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-amap",
        action="store_true",
        help="纯 wikimedia 免费档（amap 配额尽/只想白嫖 P18 时用）",
    )
    args = parser.parse_args(argv)
    factory = get_session_factory()
    if args.dry_run:
        dry_run(factory, limit=args.limit, city=args.city)
        return 0
    settings = get_settings()
    if not settings.amap_api_key:
        print(
            json.dumps(
                {"warn": "amap_api_key empty — chain degrades to wikimedia only"},
                ensure_ascii=True,
            )
        )
    stats = asyncio.run(
        backfill(
            factory,
            settings,
            limit=args.limit,
            city=args.city,
            concurrency=args.concurrency,
            no_amap=args.no_amap,
        )
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 2 if stats.get("stop") else 0


if __name__ == "__main__":
    sys.exit(main())
