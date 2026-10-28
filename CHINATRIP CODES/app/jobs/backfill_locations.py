"""POI 坐标批量补全作业（2026-10-28 backlog：无坐标行走高德 text 补齐）。

选行：location 为空 + status active/空 + 非餐饮 + KNOWN_CITIES（规划池；
池外城市 MVP 外）。优先级按 source 档（unesco>5a>intl 系>scenic>museum>
street/histown>show>amap>其余）——规划候选池主力先补，长尾后补。

逐行 search_poi(name, city=城) 取首个通过校验的命中（有坐标 + 同城相容 +
名称互含），经 PoiDetailStore.upsert 落库（fill-empty + wgs84 成对写，
v1.7 铁律，不覆盖已有值）。配额友好：--limit 上限 + AmapQuotaExhausted
即停（当日 text 配额留给 22h 抓取链）；幂等可续跑——只选无坐标行，
重跑自然续批。

用法：
    python -m app.jobs.backfill_locations [--limit 50] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re

from sqlalchemy import or_

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.agent.plan import KNOWN_CITIES
from app.services.amap_client import AmapQuotaExhaustedError
from app.services.map_provider import build_map_client
from app.services.poi_details import PoiDetailStore

logger = logging.getLogger(__name__)

# source → 补全优先档（小值先补）：名单/榜单行是规划池主力
_SOURCE_RANK = {
    "unesco": 0,
    "5a": 1,
    "tripadvisor": 2,
    "lonelyplanet": 2,
    "viator": 2,
    "curated": 2,
    "xiaohongshu": 2,
    "sygic": 2,
    "scenic": 3,
    "museum1": 4,
    "museum2": 4,
    "street": 5,
    "histown": 5,
    "show": 6,
    "amap": 7,
}

_FOOD_MARKS = ("food", "餐饮", "美食", "餐厅")


def _norm(s: str | None) -> str:
    return re.sub(r"[\s（）()\[\]【】「」·、，,。.\-—_'\"”]", "", s or "")


def _bare_city(city: str | None) -> str:
    return (city or "").strip().removesuffix("市")


def name_overlap(a: str | None, b: str | None) -> bool:
    """名称互含（≥2 字短侧），防同名异地：贡院/西湖 这类泛名靠城校验兜。"""
    a, b = _norm(a), _norm(b)
    if len(a) < 2 or len(b) < 2:
        return False
    return a in b or b in a


def city_compatible(row_city: str | None, hit_city: str | None) -> bool:
    """同城相容：高德 cityname 可能带市尾/省名前缀，去尾后互含即算。"""
    r, h = _bare_city(row_city), _bare_city(hit_city)
    if not r or not h:
        return True  # hit 未回城名时不硬拒（citylimit=true 已约束）
    return r in h or h in r


def hit_lonlat(hit: dict) -> tuple[float, float] | None:
    """命中行坐标提取，容三形：dict{lon,lat}（baidu）/ "lon,lat" 串与
    (lon, lat) 序（amap）。取不出有效数即 None。"""
    loc = hit.get("location")
    if isinstance(loc, dict):
        try:
            lon, lat = float(loc["lon"]), float(loc["lat"])
        except (KeyError, TypeError, ValueError):
            return None
        return (lon, lat)
    if isinstance(loc, (tuple, list)) and len(loc) == 2:
        try:
            return (float(loc[0]), float(loc[1]))
        except (TypeError, ValueError):
            return None
    if isinstance(loc, str):
        parts = loc.split(",")
        if len(parts) == 2:
            try:
                return (float(parts[0]), float(parts[1]))
            except ValueError:
                return None
    return None


def pick_hit(hits: list[dict], name: str, city: str | None) -> dict | None:
    """首个通过校验的命中：有坐标 + 同城相容 + 名称互含；无则 None。"""
    for hit in hits:
        if hit_lonlat(hit) is None:
            continue
        if not city_compatible(city, hit.get("city")):
            continue
        if not name_overlap(name, hit.get("name")):
            continue
        return hit
    return None


def select_rows(limit: int) -> list[Poi]:
    """无坐标规划池行，按 source 优先档排序取前 limit 行。"""
    cities: list[str] = []
    for c in KNOWN_CITIES:
        cities += [c, f"{c}市"]
    with get_session_factory()() as session:
        q = session.query(Poi).filter(
            Poi.location.is_(None),
            or_(Poi.status.is_(None), Poi.status == "active"),
            Poi.city.in_(cities),
        )
        for mark in _FOOD_MARKS:
            q = q.filter(~Poi.category.ilike(f"%{mark}%"))
        rows = q.all()
    rows.sort(key=lambda r: _SOURCE_RANK.get(r.source or "", 99))
    return rows[:limit]


async def backfill(*, limit: int, dry_run: bool = False) -> dict:
    # 走图商抽象（search_poi 同签名同 GCJ-02 出参）：MAP_PROVIDER 跟随
    # .env——amap 被 WAF 拒（bixi punish 页）时可切 baidu 续跑
    amap = build_map_client(get_settings())
    store = PoiDetailStore(session_factory=get_session_factory())
    rows = select_rows(limit)
    stats = {"selected": len(rows), "filled": 0, "missed": 0, "quota_stopped": 0}
    for row in rows:
        try:
            hits = await amap.search_poi(row.name_zh or "", city=_bare_city(row.city))
        except AmapQuotaExhaustedError:
            # 当日配额尽即停——剩余留给 22h 抓取链，明日续跑
            stats["quota_stopped"] = 1
            logger.warning("backfill_locations: amap daily quota exhausted, stopping")
            break
        except Exception:  # noqa: BLE001 — 单行失败不掀批次
            logger.warning(
                "backfill_locations: search failed for %s", row.name_zh, exc_info=True
            )
            stats["missed"] += 1
            continue
        hit = pick_hit(hits, row.name_zh or "", row.city)
        if hit is None:
            stats["missed"] += 1
            continue
        if dry_run:
            stats["filled"] += 1
            logger.info("[dry-run] would fill %s (%s)", row.name_zh, row.city)
            continue
        lon, lat = hit_lonlat(hit)
        store.upsert(
            row.source_poi_id,
            source=row.source,
            name=row.name_zh,
            city=row.city,
            address=hit.get("address"),
            location=(float(lon), float(lat)),
        )
        stats["filled"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = asyncio.run(backfill(limit=args.limit, dry_run=args.dry_run))
    print(stats)


if __name__ == "__main__":
    main()
