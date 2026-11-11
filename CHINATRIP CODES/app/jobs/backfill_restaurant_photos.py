"""Restaurants 照片批量预热作业（DESIGN poi_photos_functional_design
2026-11-11 §3-F2；2026-11-12 restaurants 回源）.

覆盖率现状：restaurants active 5,088 行 photos 0 覆盖，且全部无 amap
id（source_poi_id 空）、无 rating——走 fetch_photo_chain 新档位 v5
place/around（keyword=name_zh+去括号变体、location=行坐标、命中名且
photos 非空才收），全落空再 wikimedia P18 兜底。around 与 place/text
独立配额池、独立风控（amap_client 2026-11-03 实测结论），批量跑不撞
text 端点的 WAF 处罚。

本 job 骨架与 app.jobs.backfill_photos 同款（选行/只填空/冷却戳/熔断），
差异仅在模型与选行：
  restaurants：status='active' AND photos IS NULL AND name_zh 非空 AND
  location 非空 AND 24h 冷却外（photos_fetched_at 尝试即落戳，拉空行
  24h 内不重烧），order by id。坐标经 func.ST_AsText 出 WKT 文本、
  backfill_addresses.parse_lonlat 解析（现成提取器复用，不入 ORM
  WKB——选行即带 (lon, lat) 元组，链上 _row_lonlat 直接可用）。

写库：逐列只填空——photos 为空且链上拉到才写 photos/photos_source；
photos_fetched_at 尝试即落戳（失败也落），与点击端点一致。

配额：amap USER_DAILY_QUERY_OVER_LIMIT 首撞即停整轮（熔断语义，
fetch_photo_chain 对 AmapQuotaExhaustedError 原样上抛），明日重置续跑；
fill-empty-only + 24h 冷却保证无损续跑。

用法：
    python -m app.jobs.backfill_restaurant_photos [--limit 500]
                                                  [--city 重庆]
                                                  [--concurrency 3]
                                                  [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, or_

from app.config import get_settings
from app.db import get_session_factory
from app.jobs.backfill_addresses import parse_lonlat
from app.models import Restaurant
from app.services.amap_client import AmapClient, AmapQuotaExhaustedError
from app.services.poi_photos import fetch_photo_chain

_DEFAULT_LIMIT = 500
_DEFAULT_CONCURRENCY = 3
_QUOTA_STOP = "quota_exhausted_stop"


def select_targets(
    session_factory, *, limit: int, city: str | None = None
) -> list[NamedTuple]:
    """restaurants 回源候选：active + 无图 + 有名 + 有坐标 + 冷却外。

    返回 Row 元组（restaurant_id/name_zh/city/source/lonlat），坐标以
    (lon, lat) 元组随行携带——链上 fetch_photo_chain 经 _row_lonlat
    取用，不再二次解 WKB。
    """
    cooldown_deadline = datetime.now() - timedelta(hours=24)
    with session_factory() as session:
        q = (
            session.query(
                Restaurant.id.label("restaurant_id"),
                Restaurant.name_zh,
                Restaurant.city,
                Restaurant.source,
                func.ST_AsText(Restaurant.location).label("loc_txt"),
            )
            .filter(
                Restaurant.status == "active",
                Restaurant.photos.is_(None),
                Restaurant.name_zh.isnot(None),
                Restaurant.name_zh != "",
                Restaurant.location.isnot(None),
                or_(
                    Restaurant.photos_fetched_at.is_(None),
                    Restaurant.photos_fetched_at < cooldown_deadline,
                ),
            )
            .order_by(Restaurant.id)
            .limit(limit)
        )
        if city:
            q = q.filter(Restaurant.city.contains(city))
        return q.all()


class _Target(NamedTuple):
    restaurant_id: object
    name_zh: str
    city: str | None
    source: str | None
    # 字段名必须叫 location：fetch_photo_chain 以 getattr(row, "location")
    # 取坐标（poi_photos._row_lonlat 兼容 (lon, lat) 元组），名错位即
    # 静默跌回 v3 text（2026-11-12 真跑 0/30 命中的根因）。
    location: tuple[float, float] | None


def _targets(rows) -> list[_Target]:
    return [
        _Target(
            r.restaurant_id,
            (r.name_zh or "").strip(),
            r.city,
            r.source,
            parse_lonlat(r.loc_txt),
        )
        for r in rows
    ]


def _write_row(factory, restaurant_id, photos, source) -> list[str]:
    """逐列只填空写库；返回实际写入的列名清单。"""
    written: list[str] = []
    now = datetime.now()
    with factory() as session:
        row = session.get(Restaurant, restaurant_id)
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
        await asyncio.to_thread(_write_row, factory, t.restaurant_id, None, None)
        return
    stats["hits"] += 1
    written = await asyncio.to_thread(
        _write_row, factory, t.restaurant_id, photos, source
    )
    for col in written:
        stats["filled"][col] = stats["filled"].get(col, 0) + 1


async def backfill(factory, settings, *, limit, city, concurrency) -> dict:
    stats: dict = {
        "targets": 0,
        "hits": 0,
        "no_data": 0,
        "errors": 0,
        "filled": {},
        "stop": None,
    }
    targets = _targets(select_targets(factory, limit=limit, city=city))
    stats["targets"] = len(targets)
    amap = (
        AmapClient(key=settings.amap_api_key, timeout_seconds=10.0)
        if settings.amap_api_key
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
        description="Restaurants photos batch backfill (around + wikimedia chain)"
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--city", type=str, default=None)
    parser.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true")
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
        )
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 2 if stats.get("stop") else 0


if __name__ == "__main__":
    sys.exit(main())
