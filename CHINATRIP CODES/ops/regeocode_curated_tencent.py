# -*- coding: utf-8 -*-
"""curated 行坐标腾讯重定位（2026-11-12，用户拍板清洗百度源值的坐标部分）。

首跑 76/76 撞腾讯限流（status 120 冷却，单点测试成功后连发触发）——
本脚本待配额窗口重跑：python -I ops/regeocode_curated_tencent.py
节流 1s/次 + 指数退避重试。只更新解析成功的行，失败保留原坐标并打印。
幂等：重复跑无害（腾讯点覆盖腾讯点）。
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")

from sqlalchemy import select  # noqa: E402
from geoalchemy2 import WKTElement  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_session_factory  # noqa: E402
from app.models import Poi  # noqa: E402
from app.services.tencent_client import TencentClient  # noqa: E402
from app.services.coords import gcj02_to_wgs84  # noqa: E402

PAUSE = 1.0  # 1s/次，远低于腾讯个人 key QPS 上限


async def geo_retry(tc, addr: str):
    delay = 1.2
    for attempt in range(4):
        try:
            return await tc.geocode(addr)
        except Exception as e:  # noqa: BLE001 — 限流退避后重试
            if "Quota" in type(e).__name__ and attempt < 3:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            raise
    return None


async def main() -> int:
    st = get_settings()
    tc = TencentClient(ak=st.tencent_map_key, base_url=st.tencent_base_url,
                       timeout_seconds=st.amap_timeout_seconds)
    sf = get_session_factory()
    with sf() as s:
        rows = s.execute(select(Poi).where(
            Poi.source == "curated", Poi.status == "active", Poi.address.isnot(None)
        )).scalars().all()
    print("targets:", len(rows))
    updated, kept = 0, []
    for r in rows:
        try:
            g = await geo_retry(tc, r.address)
        except Exception as e:  # noqa: BLE001 — 记录保留原坐标
            kept.append((r.name_zh, f"{type(e).__name__}"))
            await asyncio.sleep(PAUSE)
            continue
        await asyncio.sleep(PAUSE)
        if g and g.get("lon") and g.get("lat"):
            with sf() as s2:
                row = s2.get(Poi, r.id)
                w = gcj02_to_wgs84(g["lon"], g["lat"])
                row.location = WKTElement(f"POINT({g['lon']} {g['lat']})", srid=4326)
                row.wgs84_location = WKTElement(f"POINT({w[0]} {w[1]})", srid=4326)
                s2.commit()
            updated += 1
        else:
            kept.append((r.name_zh, "no-result"))
    print(f"updated={updated} kept={len(kept)} / {len(rows)}")
    for n, why in kept:
        print("  keep-old:", n, "|", why)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
