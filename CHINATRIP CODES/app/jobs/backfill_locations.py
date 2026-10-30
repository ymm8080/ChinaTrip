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
from app.services.map_provider import build_client_chain, build_vendor
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


async def backfill_rows(
    store, clients, rows, *, dry_run: bool = False, geocoder=None
) -> dict:
    """逐行走检索链补坐标（2026-10-30 vendor_policy：amap>tencent>baidu）。

    任一家配额死即 latch 到下一家；全死才停（幂等可续）。by_vendor 记录
    每家落地域次。"""
    stats: dict = {
        "selected": len(rows),
        "filled": 0,
        "missed": 0,
        "quota_stopped": 0,
        "by_vendor": {},
    }
    dead: set[str] = set()
    geocode_dead = False
    stats["geocode_filled"] = 0
    for row in rows:
        # ④ 地址优先（2026-10-30 用户拍板「有地址就该有坐标」）：有门址的行
        # 先走正地理（百度 geocoding，独立配额池，不烧检索配额），命中即落库；
        # 未命中/配额死再走检索链按名搜。
        row_address = getattr(row, "address", None)
        # 无门址行退一级：城市+名字作为 geocode 查询（百度对地标名+城市
        # 解析可用；命中仍受下方距城心 500km 闸约束，错配不采）。
        geocode_query = row_address or (
            f"{_bare_city(row.city)}{row.name_zh or ''}"
            if (row.name_zh and _bare_city(row.city))
            else None
        )
        if (
            geocoder is not None
            and not geocode_dead
            and geocode_query
            and not getattr(row, "location", None)
        ):
            try:
                geo = await geocoder.geocode(geocode_query, city=_bare_city(row.city))
            except AmapQuotaExhaustedError:
                geocode_dead = True
                stats["geocode_quota_stopped"] = 1
                logger.warning(
                    "backfill_locations: geocode quota exhausted, "
                    "falling to search chain"
                )
            except Exception:  # noqa: BLE001 — 单行失败不掀批次
                logger.warning(
                    "backfill_locations: geocode failed for %s",
                    row.name_zh,
                    exc_info=True,
                )
            else:
                near = False
                if isinstance(geo, dict) and geo.get("lon") is not None:
                    from app.services.coords import haversine_m
                    from app.services.weather_open_meteo import CITY_COORDS

                    center = CITY_COORDS.get(_bare_city(row.city))
                    near = center is None or (
                        haversine_m(
                            float(geo["lon"]),
                            float(geo["lat"]),
                            center[1],
                            center[0],
                        )
                        / 1000.0
                        <= 500.0
                    )
                if near:
                    if dry_run:
                        stats["filled"] += 1
                        stats["geocode_filled"] += 1
                        stats["by_vendor"]["baidu_geocode"] = (
                            stats["by_vendor"].get("baidu_geocode", 0) + 1
                        )
                        logger.info(
                            "[dry-run] would geocode-fill %s (%s)",
                            row.name_zh,
                            row.city,
                        )
                        continue
                    store.upsert(
                        row.source_poi_id,
                        source=row.source,
                        name=row.name_zh,
                        city=row.city,
                        location=(float(geo["lon"]), float(geo["lat"])),
                    )
                    stats["filled"] += 1
                    stats["geocode_filled"] += 1
                    stats["by_vendor"]["baidu_geocode"] = (
                        stats["by_vendor"].get("baidu_geocode", 0) + 1
                    )
                    continue
        hit = None
        hit_vendor = None
        for client in clients:
            vendor = getattr(client, "vendor", "amap")
            if vendor in dead:
                continue
            try:
                hits = await client.search_poi(
                    row.name_zh or "", city=_bare_city(row.city)
                )
            except AmapQuotaExhaustedError:
                dead.add(vendor)
                stats["quota_stopped"] += 1
                logger.warning(
                    "backfill_locations: %s quota exhausted, falling to next vendor",
                    vendor,
                )
                continue
            except Exception:  # noqa: BLE001 — 单行失败不掀批次
                logger.warning(
                    "backfill_locations: %s search failed for %s",
                    vendor,
                    row.name_zh,
                    exc_info=True,
                )
                continue
            hit = pick_hit(hits, row.name_zh or "", row.city)
            if hit is not None:
                hit_vendor = vendor
                break
        if hit is None:
            stats["missed"] += 1
            if clients and all(getattr(c, "vendor", "amap") in dead for c in clients):
                # 全链配额死：剩余行零网络也全 miss，停（幂等可续）
                stats["stopped_no_channel"] = 1
                break
            continue
        if dry_run:
            stats["filled"] += 1
            stats["by_vendor"][hit_vendor] = stats["by_vendor"].get(hit_vendor, 0) + 1
            logger.info(
                "[dry-run] would fill %s (%s) via %s",
                row.name_zh,
                row.city,
                hit_vendor,
            )
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
        stats["by_vendor"][hit_vendor] = stats["by_vendor"].get(hit_vendor, 0) + 1
    return stats


async def backfill(
    *, limit: int, dry_run: bool = False, clients: list | None = None
) -> dict:
    # 检索链走 FUNCTION_PROVIDER_PRIORITY["search"]（amap>tencent>baidu）；
    # 单家配额烧尽自动 latch 到下一家，三家全尽才停（幂等可续跑）。
    settings = get_settings()
    if clients is None:
        clients = build_client_chain(settings, "search")
    # 地址优先轨道：百度 geocoding（独立配额池；2026-10-30 实测检索
    # 配额烧尽时仍可用）——检索三家全灭时仍能靠门址补坐标。
    geocoder = build_vendor("baidu", settings)
    store = PoiDetailStore(session_factory=get_session_factory())
    rows = select_rows(limit)
    return await backfill_rows(store, clients, rows, dry_run=dry_run, geocoder=geocoder)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--provider",
        help="强制单家图商（amap/tencent/baidu）；缺省按 vendor_policy 检索链",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    clients = None
    if args.provider:
        one = build_vendor(args.provider, get_settings())
        if one is None:
            raise SystemExit(f"provider {args.provider}: key 未配置，无法建客户端")
        clients = [one]
    stats = asyncio.run(
        backfill(limit=args.limit, dry_run=args.dry_run, clients=clients)
    )
    print(stats)


if __name__ == "__main__":
    main()
