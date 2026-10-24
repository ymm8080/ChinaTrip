"""POI 地址/营业时间每日刷新作业（CLI，v2.4.4 用户拍板）。

链序（用户拍板：携程先，高德V5后）：
  ⓪回源匹配（--match）：source!="amap" 的骨架行先走高德关键词匹配
    （名称相似度 + 距离双闸，app.services.poi_backfill）——命中则
    升级 source→"amap"、source_poi_id→高德 ID，链② 才有意义
  ①携程 sight 页（CtripHoursReader，slug 白名单 + 早停）
  ②高德 v5 place/detail（poi_id 直查，opentime_week）——仅
    source=="amap" 的行（骨架行 poi_id 非高德 ID，直查无意义）
  ③高德 v5 place/text 关键词搜索（首条；带行 GCJ-02 "lon,lat" 坐标，
    text 配额尽时 client 侧透明降级 v5 around-search）
命中即 upsert 进 pois（address/opening_hours/hours_source/hours_updated_at）；
规划端只读库（PoiDetailStore），不当场抓取。

防烧配额（2026-10-24 实测 200 连续超限）：
  quota 熔断——链②③任一遇 AmapQuotaExhaustedError(10021) 即熔断，
    本轮剩余行跳过一切高德调用（携程链照跑），跳过数计 amap_skipped
  miss 冷却——未命中行 touch hours_updated_at=now（不写 hours/source），
    24h 静默，永久缺 hours 的行不再每轮重复查询

防风控：--rotate 无 --city 时按 weekday 城轮转——库内 DISTINCT city
里第 weekday%N 个起每隔 7 取 1（一周覆盖全城、每天负载 1/7）。

用法：
    python -m app.jobs.refresh_pois [--limit 200] [--city 重庆]
        [--source chinatravel,osm] [--rotate] [--match]
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from app.config import get_settings
from app.models import Poi
from app.services.amap_client import AmapClient, AmapQuotaExhaustedError
from app.services.ctrip_hours import get_ctrip_hours
from app.services.poi_backfill import match_and_enrich
from app.services.poi_details import get_poi_detail_store

logger = logging.getLogger(__name__)


def rotate_cities(cities: list[str], weekday: int, *, span: int = 7) -> list[str]:
    """城轮转选子集（纯函数，cities/weekday 可注入测试）。

    第 weekday%N 个城市起、每隔 span 取 1 个：城市数 ≥7 时每天约 1/7
    负载、一周覆盖全城；不足 7 城时每天取 1 个循环覆盖。
    """
    n = len(cities)
    if n == 0:
        return []
    start = weekday % n
    return list(cities[start::span])


def _city_ok(row_city: str | None, city: str | None, cities: list[str] | None) -> bool:
    rc = (row_city or "").removesuffix("市")
    if city is not None and rc != (city or "").removesuffix("市"):
        return False
    if cities is not None and rc not in {(c or "").removesuffix("市") for c in cities}:
        return False
    return True


async def _match_skeletons(
    session_factory: Any, model: Any, targets: list[tuple], amap: Any
) -> tuple[dict[tuple[str, str], tuple[str, str]], dict]:
    """--match 前置：对 source!="amap" 的目标行先跑回源匹配。

    返回 (升级映射, 匹配统计)：映射键为原 (source, source_poi_id)，
    值为 ("amap", 新高德 ID)——命中升级后链② place_hours 才有意义。
    """
    upgrades: dict[tuple[str, str], tuple[str, str]] = {}
    mstats: dict = {"matched": 0, "duplicate": 0, "miss": 0, "error": 0}
    if session_factory is None:
        return upgrades, mstats
    keys = sorted({(t[3] or "", t[0]) for t in targets if (t[3] or "amap") != "amap"})
    if not keys:
        return upgrades, mstats
    row_ids: dict[tuple[str, str], Any] = {}
    rows: list[Any] = []
    with session_factory() as session:
        for src, pid in keys:
            r = (
                session.query(model)
                .filter_by(source=src, source_poi_id=pid)
                .one_or_none()
            )
            if r is not None:
                rows.append(r)
                row_ids[(src, pid)] = r.id
    mstats = await match_and_enrich(session_factory, model, rows, amap)
    with session_factory() as session:
        for key, rid in row_ids.items():
            r = session.get(model, rid)
            if r is None or (r.source or "") != "amap":
                continue
            upgrades[key] = ("amap", r.source_poi_id)
    return upgrades, mstats


async def refresh_pois(
    store,
    ctrip,
    amap,
    *,
    limit: int = 200,
    city: str | None = None,
    cities: list[str] | None = None,
    sources: tuple[str, ...] | None = None,
    match: bool = False,
    session_factory: Any = None,
) -> dict:
    targets = [
        t
        for t in store.stale_pois(limit=limit, sources=sources, city=city)
        if _city_ok(t[1], city, cities)
    ]
    stats = {
        "total": len(targets),
        "ctrip": 0,
        "amap_v5_detail": 0,
        "amap_v5_search": 0,
        "miss": 0,
        "amap_skipped": 0,
        "miss_cooldown": 0,
    }
    upgrades: dict[tuple[str, str], tuple[str, str]] = {}
    quota_dead = False
    if match:
        upgrades, mstats = await _match_skeletons(session_factory, Poi, targets, amap)
        stats["matched"] = mstats["matched"]
        stats["duplicate"] = mstats["duplicate"]
        if mstats.get("quota_exhausted"):
            # --match 阶段已烧尽配额：主循环直接进熔断态
            quota_dead = True
            stats["amap_quota_exhausted"] = True
    for poi_id, poi_city, name, poi_source, location in targets:
        upgraded = upgrades.get((poi_source or "", poi_id))
        if upgraded is not None:
            # 回源命中：骨架行已是高德 ID，链② 可直查
            poi_source, poi_id = upgraded
        hours = address = None
        source = None
        # ① 携程先（用户拍板 2026-10-19；不同供应商，quota 熔断不波及）
        try:
            hours = await ctrip.hours_for(poi_city or "", name or "")
        except Exception:
            hours = None
        if hours:
            source = "ctrip"
        # ② 高德 v5 detail（poi_id 直查；仅高德行——骨架行直查无意义）
        if not hours and amap is not None and (poi_source or "amap") == "amap":
            if quota_dead:
                stats["amap_skipped"] += 1
            else:
                out = None
                try:
                    out = await amap.place_hours(poi_id)
                except AmapQuotaExhaustedError:
                    quota_dead = True
                    stats["amap_quota_exhausted"] = True
                except Exception:
                    pass
                if isinstance(out, dict):
                    hours = out.get("opening_hours")
                    address = out.get("address")
                    if hours:
                        source = "amap_v5_detail"
        # ③ 高德 v5 关键词搜索（最终兜底；location 供 10021 降级 around）
        if not hours and amap is not None:
            if quota_dead:
                stats["amap_skipped"] += 1
            else:
                out = None
                try:
                    out = await amap.search_hours(
                        name or "", poi_city or None, location=location
                    )
                except AmapQuotaExhaustedError:
                    quota_dead = True
                    stats["amap_quota_exhausted"] = True
                except Exception:
                    pass
                if isinstance(out, dict):
                    hours = out.get("opening_hours")
                    address = address or out.get("address")
                    if hours:
                        source = "amap_v5_search"
        if hours:
            store.upsert(
                poi_id,
                city=poi_city,
                name=name,
                address=address,
                opening_hours=hours,
                hours_source=source,
            )
            stats[source] += 1
        else:
            stats["miss"] += 1
            # miss 冷却：盖戳进 24h 静默，别下轮再烧 text 配额
            store.touch_hours_checked(poi_id)
            stats["miss_cooldown"] += 1
    return stats


def _distinct_cities(session_factory: Any) -> list[str]:
    """库内 DISTINCT city（去「市」后缀、排序）——轮转候选。"""
    if session_factory is None:
        return []
    try:
        with session_factory() as session:
            rows = session.query(Poi.city).distinct().all()
    except Exception:
        logger.warning("refresh_pois: distinct cities failed", exc_info=True)
        return []
    return sorted({(r[0] or "").removesuffix("市") for r in rows if r[0]})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="刷新 POI 地址/营业时间（携程先→高德V5，落库 pois）"
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--city", help="只刷指定城市（如 重庆）")
    parser.add_argument(
        "--source",
        help="只刷指定来源，逗号分隔（如 chinatravel,osm）；缺省=全量",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="无 --city 时按 weekday 城轮转（每天 1/7 城市负载，防风控）",
    )
    parser.add_argument(
        "--match",
        action="store_true",
        help="回源校验：source!=amap 的骨架行先高德匹配升级，再补 hours",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    store = get_poi_detail_store()
    if not store.ping():
        print(
            json.dumps(
                {
                    "error": "database unreachable — "
                    "start docker db (docker compose up -d db) "
                    "or check database_url"
                },
                ensure_ascii=True,
            )
        )
        return 1
    from app.db import get_session_factory

    try:
        session_factory = get_session_factory()
    except Exception:
        session_factory = None
    amap = (
        AmapClient(
            key=settings.amap_api_key,
            base_url=settings.amap_base_url,
            timeout_seconds=settings.amap_timeout_seconds,
        )
        if settings.amap_api_key
        else None
    )
    sources = (
        tuple(s.strip() for s in args.source.split(",") if s.strip())
        if args.source
        else None
    )
    cities = None
    if args.rotate and not args.city:
        cities = _distinct_cities(session_factory)
    stats = asyncio.run(
        refresh_pois(
            store,
            get_ctrip_hours(),
            amap,
            limit=args.limit,
            city=args.city,
            cities=cities,
            sources=sources,
            match=args.match,
            session_factory=session_factory,
        )
    )
    if cities is not None:
        stats["rotated_cities"] = cities
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
