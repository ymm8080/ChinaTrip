"""POI 门址批量补齐作业（2026-10-30「地址先」）。

选行：location 非空 + address 为空 + status active/空 + 非餐饮 + KNOWN_CITIES
（规划池）。优先档 chinatravel（规划主力，2026-10-30 仅 460/1628 有地址）
> unesco > 5a > amap > 其余。

逐行逆地理 regeo（formatted_address 即门址）→ PoiDetailStore.upsert
fill-empty 落库，不覆盖已有值。regeo 与 place 检索是独立配额池——本作业
不烧检索配额；配额尽（AmapQuotaExhaustedError）即停留余量给在线链路，
幂等可续跑。主源随 MAP_PROVIDER（2026-10-30 起为百度），失败行回退高德
（用户拍板「失败行回退高德」同款）；瞬时限速退 1.5s 重试一次再放弃。

用法：
    python -m app.jobs.backfill_addresses [--limit 200] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re

from sqlalchemy import func, or_

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.agent.plan import KNOWN_CITIES
from app.services.amap_client import AmapQuotaExhaustedError
from app.services.map_provider import build_client_chain, build_vendor
from app.services.poi_details import get_poi_detail_store

logger = logging.getLogger(__name__)

# source → 补齐优先档（小值先补）：规划池主力行最先
_SOURCE_RANK = {
    "chinatravel": 0,
    "unesco": 1,
    "5a": 2,
    "tripadvisor": 3,
    "lonelyplanet": 3,
    "viator": 3,
    "curated": 3,
    "xiaohongshu": 3,
    "sygic": 3,
    "scenic": 4,
    "museum1": 4,
    "museum2": 4,
    "street": 5,
    "histown": 5,
    "show": 6,
    "baidu": 7,
    "osm": 8,
    "amap": 9,
}

_FOOD_MARKS = ("food", "餐饮", "美食", "餐厅")
_POINT_WKT_RE = re.compile(r"POINT\((\S+) (\S+)\)")
_THROTTLE_RETRY_SECONDS = 1.5


def parse_lonlat(loc_txt: str | None) -> tuple[float, float] | None:
    """ST_AsText 的 POINT(lon lat) → (lon, lat)；取不出有效数即 None。"""
    m = _POINT_WKT_RE.match(loc_txt or "")
    if not m:
        return None
    try:
        return (float(m.group(1)), float(m.group(2)))
    except ValueError:
        return None


def select_rows(limit: int) -> list[dict]:
    """有坐标无门址的规划池行，按 source 优先档排序取前 limit 行。"""
    cities: list[str] = []
    for c in KNOWN_CITIES:
        cities += [c, f"{c}市"]
    with get_session_factory()() as session:
        q = session.query(
            Poi.source_poi_id,
            Poi.city,
            Poi.name_zh,
            Poi.source,
            func.ST_AsText(Poi.location).label("loc_txt"),
        ).filter(
            Poi.location.isnot(None),
            Poi.address.is_(None),
            or_(Poi.status.is_(None), Poi.status == "active"),
            Poi.city.in_(cities),
        )
        for mark in _FOOD_MARKS:
            q = q.filter(~Poi.category.ilike(f"%{mark}%"))
        rows = [
            {
                "poi_id": r[0],
                "city": r[1],
                "name": r[2],
                "source": r[3],
                "lonlat": parse_lonlat(r[4]),
            }
            for r in q.all()
        ]
    rows = [r for r in rows if r["lonlat"] is not None]
    rows.sort(key=lambda r: _SOURCE_RANK.get(r["source"] or "", 99))
    return rows[:limit]


async def _regeo_once(client, lonlat: tuple[float, float]):
    """单行 regeo；配额尽返回 "quota" 哨兵，瞬时限速退 1.5s 重试一次。"""
    try:
        return await client.regeo(lon=lonlat[0], lat=lonlat[1])
    except AmapQuotaExhaustedError:
        return "quota"
    except Exception:  # noqa: BLE001 「当前并发量已超…」是临时限速非配额（2026-10-30 实测）
        await asyncio.sleep(_THROTTLE_RETRY_SECONDS)
        try:
            return await client.regeo(lon=lonlat[0], lat=lonlat[1])
        except AmapQuotaExhaustedError:
            return "quota"
        except Exception:  # noqa: BLE001
            logger.warning(
                "backfill_addresses: regeo failed for %s", lonlat, exc_info=True
            )
            return None


async def backfill_addresses(store, clients, *, rows, dry_run=False) -> dict:
    """逐行 regeo 链补门址（fill-empty；2026-10-30 vendor_policy：
    baidu>amap>tencent）。任一家配额死 latch 下一家；全死才停（幂等可续）。"""
    stats: dict = {
        "selected": len(rows),
        "filled": 0,
        "missed": 0,
        "quota_stopped": 0,
        "stopped_no_channel": 0,
        "by_vendor": {},
    }
    dead: set[str] = set()
    for row in rows:
        address = None
        used_vendor = None
        for client in clients:
            vendor = getattr(client, "vendor", "amap")
            if vendor in dead:
                continue
            rg = await _regeo_once(client, row["lonlat"])
            if rg == "quota":
                dead.add(vendor)
                stats["quota_stopped"] += 1
                continue
            address = rg.get("address") if isinstance(rg, dict) else None
            if address:
                used_vendor = vendor
                break
        if not address:
            stats["missed"] += 1
            if clients and all(getattr(c, "vendor", "amap") in dead for c in clients):
                # 全链配额死：剩余行零网络也全 miss，停（幂等可续）；
                # 纯失败（瞬时限速重试仍炸）不停——下一行可能自愈
                stats["stopped_no_channel"] = 1
                break
            continue
        if dry_run:
            stats["filled"] += 1
            stats["by_vendor"][used_vendor] = stats["by_vendor"].get(used_vendor, 0) + 1
            logger.info(
                "[dry-run] would fill address for %s (%s) via %s",
                row["name"],
                row["city"],
                used_vendor,
            )
            continue
        store.upsert(
            row["poi_id"],
            source=row["source"],
            city=row["city"],
            name=row["name"],
            address=address,
        )
        stats["filled"] += 1
        stats["by_vendor"][used_vendor] = stats["by_vendor"].get(used_vendor, 0) + 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--provider",
        help="强制单家图商（baidu/amap/tencent）；缺省按 vendor_policy regeo 链",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    store = get_poi_detail_store()
    # regeo 链（2026-10-30 vendor_policy）：baidu（实测最宽裕）>amap>tencent；
    # --provider 可强制单家。
    if args.provider:
        one = build_vendor(args.provider, settings)
        if one is None:
            raise SystemExit(f"provider {args.provider}: key 未配置，无法建客户端")
        clients = [one]
    else:
        clients = build_client_chain(settings, "regeo")
    rows = select_rows(args.limit)
    stats = asyncio.run(
        backfill_addresses(store, clients, rows=rows, dry_run=args.dry_run)
    )
    print(json.dumps(stats, ensure_ascii=True))


if __name__ == "__main__":
    main()
