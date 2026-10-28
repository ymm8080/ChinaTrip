"""POI 富化·高德 detail 确定性行（复用 AmapClient.place_hours）。

目标列：phone/business_area/photos/opening_hours/rating（全部来自
v5 place/detail 的 business+photos 块，确定性数据，无 LLM 参与）。

只处理 source='amap' 且 source_poi_id 非空的行——别的 source 没有
高德 id，没处查。逐列只填空，来源标记 *_source='amap'。

配额：个人 key 日配额会 USER_DAILY_QUERY_OVER_LIMIT（2026-10-25 实测
烧尽）；首撞即停整轮（熔断语义），明日重置后重跑即可，fill-empty-only
保证无损续跑。企业认证升级配额是根治（在用户侧）。

用法：
    python -m app.jobs.enrich_amap_detail [--limit 5000] [--concurrency 3] [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from typing import NamedTuple

from sqlalchemy import or_

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.amap_client import AmapClient, AmapQuotaExhaustedError

_DEFAULT_LIMIT = 5000
_DEFAULT_CONCURRENCY = 3
_QUOTA_STOP = "quota_exhausted_stop"


def select_targets(session_factory, *, limit: int) -> list[Poi]:
    with session_factory() as session:
        return (
            session.query(Poi)
            .filter(
                Poi.status == "active",
                Poi.source == "amap",
                Poi.source_poi_id.isnot(None),
                or_(
                    Poi.phone.is_(None),
                    Poi.business_area.is_(None),
                    Poi.photos.is_(None),
                    Poi.opening_hours.is_(None),
                    Poi.rating.is_(None),
                ),
            )
            .order_by(Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
            .all()
        )


class _Target(NamedTuple):
    poi_id: object
    amap_id: str
    name: str


def _write_row(factory, poi_id, r: dict) -> list[str]:
    """逐列只填空写库；返回实际写入的列名清单。"""
    written: list[str] = []
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return written
        if row.phone is None and r.get("tel"):
            row.phone = str(r["tel"]).strip()[:50]
            written.append("phone")
        if row.business_area is None and r.get("business_area"):
            row.business_area = str(r["business_area"]).strip()[:50]
            written.append("business_area")
        if row.photos is None and r.get("photos"):
            row.photos = r["photos"]
            written.append("photos")
        if row.opening_hours is None and r.get("opening_hours"):
            row.opening_hours = str(r["opening_hours"]).strip()[:200]
            row.hours_source = "amap"
            written.append("opening_hours")
        if row.rating is None and r.get("rating"):
            try:
                rv = float(r["rating"])
            except (TypeError, ValueError):
                rv = None
            if rv is not None and 0 <= rv <= 5:
                row.rating = rv
                row.rating_source = "amap"
                written.append("rating")
        if written:
            session.commit()
    return written


async def _process_row(
    client: AmapClient, factory, t: _Target, sem: asyncio.Semaphore, stats: dict
) -> None:
    async with sem:
        try:
            r = await client.place_hours(t.amap_id)
        except AmapQuotaExhaustedError:
            stats["stop"] = _QUOTA_STOP  # 首撞即停，明日重置再跑
            return
        except Exception as exc:
            stats["errors"] += 1
            stats["error_kinds"][type(exc).__name__] = (
                stats["error_kinds"].get(type(exc).__name__, 0) + 1
            )
            return
    if not r or not any(
        r.get(k) for k in ("tel", "business_area", "photos", "opening_hours", "rating")
    ):
        stats["no_data"] += 1
        return
    stats["hits"] += 1
    written = await asyncio.to_thread(_write_row, factory, t.poi_id, r)
    for col in written:
        stats["filled"][col] = stats["filled"].get(col, 0) + 1


async def enrich(factory, settings, *, limit: int, concurrency: int) -> dict:
    stats = {
        "targets": 0,
        "hits": 0,
        "no_data": 0,
        "errors": 0,
        "error_kinds": {},
        "filled": {},
        "stop": None,
    }
    rows = select_targets(factory, limit=limit)
    stats["targets"] = len(rows)
    targets = [
        _Target(r.id, r.source_poi_id, (r.name_zh or "").strip())
        for r in rows
        if r.source_poi_id
    ]
    client = AmapClient(key=settings.amap_api_key, timeout_seconds=10.0)
    sem = asyncio.Semaphore(max(1, concurrency))
    await asyncio.gather(
        *(_process_row(client, factory, t, sem, stats) for t in targets)
    )
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int) -> None:
    rows = select_targets(session_factory, limit=limit)
    print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Amap detail enrichment (deterministic)"
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    factory = get_session_factory()
    if args.dry_run:
        dry_run(factory, limit=args.limit)
        return 0
    settings = get_settings()
    if not settings.amap_api_key:
        print(json.dumps({"error": "amap_api_key is empty"}, ensure_ascii=True))
        return 1
    stats = asyncio.run(
        enrich(factory, settings, limit=args.limit, concurrency=args.concurrency)
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 2 if stats.get("stop") else 0


if __name__ == "__main__":
    sys.exit(main())
