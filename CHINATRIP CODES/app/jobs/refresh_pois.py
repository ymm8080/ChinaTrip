"""POI 地址/营业时间每日刷新作业（CLI，v2.4.4 用户拍板）。

链序（用户拍板：携程先，高德V5后）：
  ①携程 sight 页（CtripHoursReader，slug 白名单 + 早停）
  ②高德 v5 place/detail（poi_id 直查，opentime_week）
  ③高德 v5 place/text 关键词搜索（首条）
命中即 upsert 进 pois（address/opening_hours/hours_source/hours_updated_at）；
规划端只读库（PoiDetailStore），不当场抓取。

用法：
    python -m app.jobs.refresh_pois [--limit 200] [--city 重庆]
"""

import argparse
import asyncio
import json
import sys

from app.config import get_settings
from app.services.amap_client import AmapClient
from app.services.ctrip_hours import get_ctrip_hours
from app.services.poi_details import get_poi_detail_store


async def refresh_pois(
    store, ctrip, amap, *, limit: int = 200, city: str | None = None
) -> dict:
    targets = [
        t
        for t in store.stale_pois(limit=limit)
        if city is None or (t[1] or "").removesuffix("市") == city.removesuffix("市")
    ]
    stats = {
        "total": len(targets),
        "ctrip": 0,
        "amap_v5_detail": 0,
        "amap_v5_search": 0,
        "miss": 0,
    }
    for poi_id, poi_city, name in targets:
        hours = address = None
        source = None
        # ① 携程先（用户拍板 2026-10-19）
        try:
            hours = await ctrip.hours_for(poi_city or "", name or "")
        except Exception:
            hours = None
        if hours:
            source = "ctrip"
        # ② 高德 v5 detail（poi_id 直查）
        if not hours and amap is not None:
            try:
                out = await amap.place_hours(poi_id)
            except Exception:
                out = None
            if isinstance(out, dict):
                hours = out.get("opening_hours")
                address = out.get("address")
                if hours:
                    source = "amap_v5_detail"
        # ③ 高德 v5 关键词搜索（最终兜底）
        if not hours and amap is not None:
            try:
                out = await amap.search_hours(name or "", poi_city or None)
            except Exception:
                out = None
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
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="刷新 POI 地址/营业时间（携程先→高德V5，落库 pois）"
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--city", help="只刷指定城市（如 重庆）")
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
    amap = (
        AmapClient(
            key=settings.amap_api_key,
            base_url=settings.amap_base_url,
            timeout_seconds=settings.amap_timeout_seconds,
        )
        if settings.amap_api_key
        else None
    )
    stats = asyncio.run(
        refresh_pois(
            store,
            get_ctrip_hours(),
            amap,
            limit=args.limit,
            city=args.city,
        )
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
