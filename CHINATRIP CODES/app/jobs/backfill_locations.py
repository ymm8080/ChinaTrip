"""POI 坐标批量补全作业（2026-10-28 backlog：无坐标行走高德 text 补齐）。

选行：location 为空 + status active/空 + 非餐饮 + 城市注册表（poi_city
canonical 411=解析器同一真源;2026-11-02 从 plan.KNOWN_CITIES 226 统一——
505 行 rank≤5 曾被 226 闸住补不进,规划宇宙不动）;池外城市 MVP 外）。
优先级按 source 档（unesco>5a>intl 系/预约名单>
intl 系/scenic>国保/遗址公园/museum>名村/street/histown>show>
amap/baidu>4a(2026-11-01 用户拍板先放)>chinatravel 长尾）——规划候选池
主力先补，长尾后补（2026-11-01：4a/guobao8/relicpark/histvillage/
intl/reservation 曾落 99 档与长尾混排，
按 master backlog #4/#9 入档）。

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
from app.services.amap_client import AmapQuotaExhaustedError
from app.services.city_fallback import is_city_fallback_point, is_fallback_address
from app.services.map_provider import (
    build_client_chain,
    build_geocode_chain,
    build_vendor,
)
from app.services.poi_city import known_cities
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
    "intl": 2,
    "reservation": 2,
    "4a": 8,  # 2026-11-01 用户拍板「4a 先放一下」:降档到长尾前
    "scenic": 3,
    "guobao8": 4,
    "relicpark": 4,
    "museum1": 4,
    "museum2": 4,
    "histvillage": 5,
    "street": 5,
    "histown": 5,
    "show": 6,
    "amap": 7,
    "baidu": 7,
    "ctrip": 7,
    "chinatravel": 9,
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


def order_backfill_rows(rows: list[Poi]) -> list[Poi]:
    """排序：source 优先档 → 档内城市热度（核心 40 城）→ 名称.

    2026-11-03 数据债 P1-1「城市热度×tier」：同档（如 museum）长尾里
    成都/西安等计划核心城的行入池价值高，先于县域行吃当日检索配额。
    核心城 = plan.KNOWN_CITIES/weather.CITY_ADCODES 字典前部 40（两处
    同源约定：核心 40 城恒保持前部，2026-10-30 系统性扩容后沿用）。
    """
    from app.services.weather import CITY_ADCODES

    hot = frozenset(tuple(CITY_ADCODES)[:40])

    def key(r: Poi) -> tuple[int, int, str]:
        return (
            _SOURCE_RANK.get(r.source or "", 99),
            0 if _bare_city(r.city) in hot else 1,
            r.name_zh or "",
        )

    return sorted(rows, key=key)


def select_rows(limit: int) -> list[Poi]:
    """无坐标规划池行，按 source 优先档排序取前 limit 行。"""
    cities: list[str] = []
    for c in sorted(known_cities()):
        cities += [c, f"{c}市"]
    with get_session_factory()() as session:
        q = session.query(Poi).filter(
            Poi.location.is_(None),
            or_(Poi.status.is_(None), Poi.status == "active"),
            Poi.city.in_(cities),
        )
        # 非餐饮：NOT ILIKE 遇 category NULL 求值为 NULL，会把无类别骨架行
        # 整批误排除（2026-10-30 修正）——NULL 类别不是餐饮，须保留。
        q = q.filter(
            or_(
                Poi.category.is_(None),
                *[~Poi.category.ilike(f"%{mark}%") for mark in _FOOD_MARKS],
            )
        )
        rows = q.all()
    return order_backfill_rows(rows)[:limit]


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
    # 回退点入库闸计数（P1#1，2026-11-04）：geocode/检索命中城市回退点、
    # 行地址命中回退地址族，分别计数供台账观察。
    stats["geocode_fallback_rejected"] = 0
    stats["search_fallback_rejected"] = 0
    stats["fallback_addr_skipped"] = 0
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
        # 地址同型闸（P1#1，2026-11-04）：行地址=geocoder 回退地址族
        # （「渝中区上清寺」系=政府驻地）——geocode 它必然回到回退点，
        # 且地址本身已投毒（backlog #5 回源面）：不烧配额，直接退检索链
        # 按名搜（名字没投毒）。
        fallback_addr = bool(row_address) and is_fallback_address(row_address, row.city)
        if fallback_addr:
            stats["fallback_addr_skipped"] += 1
            logger.warning(
                "backfill_locations: fallback-family address on %s (%s), "
                "geocode track skipped",
                row.name_zh,
                row.city,
            )
        if (
            geocoder is not None
            and not geocode_dead
            and geocode_query
            and not fallback_addr
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
                    if near and is_city_fallback_point(
                        geo["lon"], geo["lat"], row.city
                    ):
                        # 回退点闸（P1#1，2026-11-04）：解析点=城市 gov 回退
                        # 点→拒绝不入库，退检索链按名搜。回退点距城心 0km
                        # 恒过 500km 闸，正是 181 行投毒的根因路径。
                        stats["geocode_fallback_rejected"] += 1
                        logger.warning(
                            "backfill_locations: geocode city fallback point "
                            "rejected for %s (%s)",
                            row.name_zh,
                            row.city,
                        )
                        near = False
                if near:
                    if dry_run:
                        stats["filled"] += 1
                        stats["geocode_filled"] += 1
                        _vendor = getattr(geocoder, "last_vendor", None) or getattr(
                            geocoder, "vendor", "baidu"
                        )
                        _label = f"{_vendor}_geocode"
                        stats["by_vendor"][_label] = (
                            stats["by_vendor"].get(_label, 0) + 1
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
                    _vendor = getattr(geocoder, "last_vendor", None) or getattr(
                        geocoder, "vendor", "baidu"
                    )
                    _label = f"{_vendor}_geocode"
                    stats["by_vendor"][_label] = stats["by_vendor"].get(_label, 0) + 1
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
            if geocode_dead and (
                not clients
                or all(getattr(c, "vendor", "amap") in dead for c in clients)
            ):
                # geocode 配额死 + 检索链无活源：剩余行零网络也全 miss，
                # 停（幂等可续）且不记 miss——这是配额烧尽不是确定性未命中，
                # 写台账会堵死次日配额恢复后的重试（2026-11-03）。
                stats["stopped_no_channel"] = 1
                break
            stats["missed"] += 1
            if clients and all(getattr(c, "vendor", "amap") in dead for c in clients):
                # 全链配额死：剩余行零网络也全 miss，停（幂等可续）
                stats["stopped_no_channel"] = 1
                break
            continue
        lon, lat = hit_lonlat(hit)
        if is_city_fallback_point(lon, lat, row.city):
            # 回退点闸（P1#1，2026-11-04）：检索命中落城市回退点（同名
            # gov POI 类命中）→拒绝不落库，不计数 filled。
            stats["search_fallback_rejected"] += 1
            logger.warning(
                "backfill_locations: search hit at city fallback point "
                "rejected for %s (%s)",
                row.name_zh,
                row.city,
            )
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
    # 地址优先轨道：baidu geocoding 为主（独立配额池；2026-10-30 实测检索
    # 配额烧尽时仍可用），amap geocode 兜底（独立配额池+独立风控；2026-11-03
    # 实测 place 被 bixi WAF deny 时 geocode 仍正常）——检索三家全灭时仍能
    # 靠门址补坐标。
    geocoder = build_geocode_chain(settings)
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
