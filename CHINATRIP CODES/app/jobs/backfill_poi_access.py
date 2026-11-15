"""pois.access_* 回填：城心 → POI 的公共交通最优方案（2026-11-15）。

用户拍板「远郊景点（慕田峪这类）要有景点转线大巴/地铁/火车的信息，POIS
是否加一列 TRANSPORTATION」——落成一组摘要列（w12_0037），本任务负责回填：

* 起点固定为城心（``weather_open_meteo.CITY_COORDS``，缺锚城市跳过）；
* 走本仓既有 transit 商链（baidu > amap，见 ``map_provider``），取最快方案，
  归一逻辑在 ``app.services.poi_access.summarize``（纯函数，有单测）；
* 只填 >min-km 的点（默认 15km）——近点打车/步行就够，省配额；按距城心
  由远到近跑，限量时优先覆盖最需要的远郊件；
* 只填空：``access_updated_at`` 非空的行默认不动（``--force`` 重算）。

服务类行（hotel/food/transport/service）不参与——它们不是「去玩」的目的地。

用法：
    python -m app.jobs.backfill_poi_access [--city 北京] [--limit 200]
        [--min-km 15] [--sleep 0.2] [--concurrency 4] [--force] [--dry-run]

并发：商链单次 8–30s（百度偶发超时回落高德），串行跑全库 3000+ 个点要一天
多；默认 4 路并发（同一 AK 不宜再高，配额打穿会按日 latch 到另一家）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime

from sqlalchemy import bindparam, text

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.itinerary.models import GeoPoint
from app.services.itinerary.rules import haversine_km
from app.services.map_provider import build_client_chain
from app.services.poi_access import summarize
from app.services.vendor_chain import run_vendor_chain
from app.services.weather_open_meteo import CITY_COORDS

logger = logging.getLogger(__name__)

#: 不参与回填的类别（服务类行：住/吃/交通设施/通用服务）。
_EXCLUDED_CATEGORIES = ("hotel", "food", "transport", "service")

_SELECT_SQL = """
SELECT id, name_zh, city, category,
       ST_Y(location::geometry), ST_X(location::geometry),
       access_updated_at, access_mode
FROM pois
WHERE (status IS NULL OR status = 'active')
  AND location IS NOT NULL
  AND (category IS NULL OR category NOT IN :excluded)
ORDER BY id
"""


def _candidates(
    factory,
    *,
    city: str | None,
    min_km: float,
    limit: int,
    force: bool,
    only_modes: tuple[str, ...] = (),
) -> list[tuple]:
    """远郊候选（按距城心由远到近），限量取前 N。

    ``only_modes`` = 只重算已回填成这些方式的行（补列/修口径时用，避免把
    3000+ 个点全部重跑一遍烧配额）。
    """
    with factory() as session:
        rows = session.execute(
            text(_SELECT_SQL)
            .bindparams(bindparam("excluded", expanding=True))
            .params(excluded=tuple(_EXCLUDED_CATEGORIES))
        ).all()
    out: list[tuple] = []
    for pid, name, row_city, category, lat, lon, updated, row_mode in rows:
        if updated is not None and not force:
            continue
        if only_modes and (row_mode or "") not in only_modes:
            continue
        if city and (row_city or "") not in (city, city + "市"):
            continue
        anchor = CITY_COORDS.get(str(row_city or "").strip())
        if not anchor or lat is None or lon is None:
            continue
        center = GeoPoint(lon=float(anchor[1]), lat=float(anchor[0]))
        here = GeoPoint(lon=float(lon), lat=float(lat))
        km = haversine_km(center, here)
        if km < min_km:
            continue
        out.append((pid, name, row_city, km, float(lon), float(lat)))
    out.sort(key=lambda r: r[3], reverse=True)
    return out[:limit]


async def _plans_for(chain: list, *, city: str, lon: float, lat: float, latch: dict):
    """跑一次商链，返回 (plans, 实际落地图商)。"""
    origin = CITY_COORDS.get(city)
    if not origin:
        return [], None
    saw: dict[str, str] = {}

    def call(client):
        saw["vendor"] = getattr(client, "vendor", "amap")
        return client.transit_route(
            f"{float(origin[1]):.6f},{float(origin[0]):.6f}",
            f"{lon:.6f},{lat:.6f}",
            city=city,
            cityd=city,
        )

    plans = await run_vendor_chain(chain, call, latch=latch, function="transit")
    if not isinstance(plans, list):
        return [], saw.get("vendor")
    return plans, saw.get("vendor")


async def run(
    *,
    city: str | None = None,
    limit: int = 200,
    min_km: float = 15.0,
    sleep: float = 0.2,
    concurrency: int = 4,
    force: bool = False,
    dry_run: bool = False,
    only_modes: tuple[str, ...] = (),
) -> int:
    factory = get_session_factory()
    rows = _candidates(
        factory,
        city=city,
        min_km=min_km,
        limit=limit,
        force=force,
        only_modes=only_modes,
    )
    by_city: dict[str, int] = {}
    for row in rows:
        by_city[str(row[2])] = by_city.get(str(row[2]), 0) + 1
    print(f"候选 {len(rows)} 个（>{min_km:g}km，城心口径）：{by_city}")

    settings = get_settings()
    chain = build_client_chain(settings, "transit")
    if not chain:
        print("无可用 transit 图商（检查 AMAP/BAIDU key）")
        return 0

    latch: dict[str, str] = {}
    sem = asyncio.Semaphore(max(1, concurrency))
    stats = {"written": 0, "failed": 0}

    async def one(row) -> None:
        pid, name, row_city, km, lon, lat = row
        async with sem:
            plans, vendor = await _plans_for(
                chain, city=str(row_city), lon=lon, lat=lat, latch=latch
            )
            summary = summarize(plans, poi_point=(lon, lat))
            if not summary:
                stats["failed"] += 1
                print(f"  ✗ {row_city} {name}（{km:.0f}km）无方案")
                await asyncio.sleep(sleep)
                return
            if dry_run:
                stats["written"] += 1
                print(f"  · {row_city} {name}（{km:.0f}km）{summary['access_note']}")
                await asyncio.sleep(sleep)
                return
            with factory() as session:
                db_row = session.get(Poi, pid)
                if db_row is None or (db_row.access_updated_at and not force):
                    return
                for key, value in summary.items():
                    setattr(db_row, key, value)
                db_row.access_source = f"{vendor}-transit" if vendor else "transit"
                db_row.access_updated_at = datetime.now()
                session.commit()
            stats["written"] += 1
            print(f"  ✓ {row_city} {name}（{km:.0f}km）{summary['access_note']}")
            await asyncio.sleep(sleep)

    await asyncio.gather(*(one(row) for row in rows))
    print(f"写入 {stats['written']} / 失败 {stats['failed']} / 候选 {len(rows)}")
    return stats["written"]


def main() -> None:
    parser = argparse.ArgumentParser(description="POI 到达方式回填（城心口径）")
    parser.add_argument("--city", default=None, help="只跑某城（默认全城）")
    parser.add_argument("--limit", type=int, default=200, help="本次最多回填条数")
    parser.add_argument(
        "--min-km", type=float, default=15.0, help="只回填距城心超过此距离的点"
    )
    parser.add_argument("--sleep", type=float, default=0.2, help="每条之间歇秒")
    parser.add_argument(
        "--concurrency", type=int, default=4, help="并发条数（默认 4，同一 AK 别调高）"
    )
    parser.add_argument("--force", action="store_true", help="重算已填行")
    parser.add_argument(
        "--only-modes",
        default="",
        help="只重算已回填成这些方式的行（逗号分隔，如 train,shuttle,ferry）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(
        run(
            city=args.city,
            limit=args.limit,
            min_km=args.min_km,
            sleep=args.sleep,
            concurrency=args.concurrency,
            force=args.force,
            only_modes=tuple(
                m.strip() for m in args.only_modes.split(",") if m.strip()
            ),
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
