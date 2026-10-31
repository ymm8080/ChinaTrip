"""miss 台账行的 geocode 变体救援（一次性 ops 脚本）。

台账行的首次尝试用的是固定查询式（门址 或 城市+名字）；本脚本换查询
变体再试一轮——名字直查 / 纯城市+名字（剥掉 show 行的「郑州（中牟）」
括号尾）——命中校验加严：省级/城市级结果一律不采（城心太糙），无城心
参照的行再拒 区县/乡镇/NoClass。走 backfill_rows 既有落库路径
（fill-empty + wgs84 成对写），救回的行从台账移除。

用法：python ops/rescue_miss_coords.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LEDGER = Path(__file__).resolve().parent / "backfill_coords_missed.txt"

# 精度过粗不采的 level：省级/城市级是城心兜底；无城心距离闸时再拒次级
_REJECT_ALWAYS = {"省份", "城市"}
_REJECT_NO_CENTER = {"区县", "乡镇", "NoClass"}


def _variants(row) -> list[str]:
    name = (row.name_zh or "").strip()
    city = (row.city or "").strip()
    bare = city.removesuffix("市").split("（")[0].strip()
    out: list[str] = []
    if name:
        out.append(name)  # 名字直查：百度对地标名解析可用
    if bare and name and f"{bare}{name}" != name:
        out.append(f"{bare}{name}")
    addr = getattr(row, "address", None)
    if addr and addr.strip():
        out.append(addr.strip())
    return list(dict.fromkeys(q for q in out if q))


class VariantGeocoder:
    """包一层百度 geocode：按变体序尝试，命中校验加严。"""

    def __init__(self, inner, row):
        self.inner = inner
        self.row = row
        self.tries: list[str] = []

    async def geocode(self, address: str, *, city: str | None = None):
        from app.services.coords import haversine_m
        from app.services.weather_open_meteo import CITY_COORDS

        city_key = (self.row.city or "").removesuffix("市").split("（")[0]
        center = CITY_COORDS.get(city_key)
        last = None
        for q in _variants(self.row):
            self.tries.append(q)
            try:
                geo = await self.inner.geocode(q, city=city)
            except Exception:  # noqa: BLE001 — 单变体失败继续下一个
                continue
            last = geo
            if not (isinstance(geo, dict) and geo.get("lon") is not None):
                continue
            level = (geo.get("level") or "").strip()
            if level in _REJECT_ALWAYS:
                continue
            if center is None:
                if level in _REJECT_NO_CENTER:
                    continue
            else:
                d_km = (
                    haversine_m(
                        float(geo["lon"]), float(geo["lat"]), center[1], center[0]
                    )
                    / 1000.0
                )
                if d_km > 500.0:
                    continue
            return geo
        return last


async def main() -> None:
    from app.config import get_settings
    from app.db import get_session_factory
    from app.jobs.backfill_locations import backfill_rows, name_overlap  # noqa: F401
    from app.models import Poi
    from app.services.map_provider import build_vendor
    from app.services.poi_details import PoiDetailStore

    ledger: dict[str, str] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if parts:
            ledger[parts[0]] = parts[1] if len(parts) > 1 else ""

    with get_session_factory()() as session:
        rows = (
            session.query(Poi)
            .filter(Poi.location.is_(None), Poi.source_poi_id.in_(list(ledger)))
            .all()
        )
    print(f"ledger rows still null: {len(rows)}")

    settings = get_settings()
    geocoder = build_vendor("baidu", settings)
    store = PoiDetailStore(session_factory=get_session_factory())
    rescued: list[str] = []
    for row in rows:
        stats = await backfill_rows(
            store, [], [row], geocoder=VariantGeocoder(geocoder, row)
        )
        if stats.get("filled"):
            rescued.append(row.source_poi_id)
            print(f"  RESCUED {row.city} | {row.name_zh}")
        else:
            print(
                f"  still-miss {row.city} | {row.name_zh} | "
                f"tries={getattr(geocoder, 'tries', [])}"
            )

    # 台账移除已救回行
    if rescued:
        kept = [
            ln for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        keep = [ln for ln in kept if ln.split(None, 1)[0] not in set(rescued)]
        LEDGER.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    now = len(kept) - len(rescued) if rescued else len(kept)
    print(f"rescued {len(rescued)}/{len(rows)}; ledger now {now}")


if __name__ == "__main__":
    asyncio.run(main())
