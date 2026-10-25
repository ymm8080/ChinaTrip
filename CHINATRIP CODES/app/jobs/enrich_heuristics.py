"""POI 富化·类别启发式（indoor/rain_ok + duration 地板值，零联网）。

0009 流 item 11 落地（本会话代做，PROGRESS 已注记）。三段：
  1. 有 category 的行：类别→indoor/rain_ok 直接映射；
  2. category 为空的行：name_zh 关键词保守分类，高置信才落 category
     （category 无 source 列，落错的代价=分类元数据不准，可接受；
     置信不足的一律不碰）；
  3. duration 地板值（--with-duration 才启用）：类别/名称→分钟下限。
     **必须最后跑**——先跑会占坑挡住携程/高德的真实时长（只填空语义）。

映射原则（宁缺毋滥）：
  * indoor=True 仅限明确的室内馆；indoor=False 仅限明确户外；
    混合体（古镇/街区/寺庙群）一律留 None 给未来真数据。
  * rain_ok=True=雨天可游（室内/溶洞）；False=雨天体验受损；
    拿不准留 None。
  * duration 地板值是"规划下限"不是事实主张，标 duration_source='heuristic'。

用法：
    python -m app.jobs.enrich_heuristics [--limit 5000] [--with-duration] [--dry-run]
"""

import argparse
import json
import sys

from sqlalchemy import or_

from app.db import get_session_factory
from app.models import Poi

_DEFAULT_LIMIT = 5000

# 类别 → (indoor, rain_ok)；None=拿不准不填
_CATEGORY_MAP = {
    "museum": (True, True),
    "theme_park": (False, False),
    "park": (False, False),
    "nature": (False, False),
    "viewpoint": (False, None),
    "attraction": (None, None),
}

# 名称关键词 → 判定；顺序即优先级（首个命中即停）
_INDOOR_HINTS = (
    "博物馆",
    "纪念馆",
    "美术馆",
    "科技馆",
    "海洋馆",
    "水族馆",
    "展览馆",
    "陈列馆",
    "天文馆",
    " Planetarium",
    "蜡像馆",
    "规划馆",
)
_OUTDOOR_HINTS = (
    "山",
    "峡",
    "谷",
    "岛",
    "湖",
    "海",
    "滩",
    "草原",
    "湿地",
    "花海",
    "漂流",
    "瀑布",
    "森林公园",
    "雪场",
    "滑雪",
    "热雪",
)
_CAVE_HINTS = ("溶洞", "洞窟", "石窟")
_URBAN_HINTS = (
    "古镇",
    "古街",
    "街区",
    "步行街",
    "老街",
    "城墙",
    "大道",
    "大桥",
    "广场",
)  # noqa: E501
_DURATION_FLOOR = {
    "museum": 90,
    "theme_park": 240,
    "park": 90,
    "nature": 180,
    "viewpoint": 30,
    "attraction": 90,
}


def _classify(
    name: str, category: str | None
) -> tuple[str | None, bool | None, bool | None, int | None]:
    """返回 (category, indoor, rain_ok, duration_floor)；拿不准的为 None。"""
    cat = category
    indoor = rain_ok = None
    floor = None
    if cat in _CATEGORY_MAP:
        indoor, rain_ok = _CATEGORY_MAP[cat]
    if indoor is None and cat is None:
        # 高置信室内：名称带明确馆字
        if any(h in name for h in _INDOOR_HINTS):
            cat, indoor, rain_ok = "museum", True, True
        elif any(h in name for h in _CAVE_HINTS):
            cat, indoor, rain_ok = "nature", False, True
        elif any(h in name for h in _OUTDOOR_HINTS):
            cat, indoor, rain_ok = "nature", False, False
        elif any(h in name for h in _URBAN_HINTS):
            cat, indoor, rain_ok = "attraction", False, None
    if cat is not None:
        floor = _DURATION_FLOOR.get(cat)
    return cat, indoor, rain_ok, floor


def select_targets(session_factory, *, limit: int, with_duration: bool) -> list[Poi]:
    with session_factory() as session:
        conds = [Poi.category.is_(None)]
        if with_duration:
            conds.append(Poi.suggested_duration_min.is_(None))
        return (
            session.query(Poi)
            .filter(Poi.status == "active", or_(*conds))
            .limit(limit)
            .all()
        )


def _write_row(factory, poi_id, *, indoor, rain_ok, category, floor) -> list[str]:
    written: list[str] = []
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return written
        if row.indoor is None and indoor is not None:
            row.indoor = indoor
            written.append("indoor")
        if row.rain_ok is None and rain_ok is not None:
            row.rain_ok = rain_ok
            written.append("rain_ok")
        if row.category is None and category is not None:
            row.category = category
            written.append("category")
        if row.suggested_duration_min is None and floor is not None:
            row.suggested_duration_min = floor
            row.duration_source = "heuristic"
            written.append("duration")
        if written:
            session.commit()
    return written


def enrich(factory, *, limit: int, with_duration: bool) -> dict:
    stats: dict = {"targets": 0, "filled": {}, "samples": []}
    rows = select_targets(factory, limit=limit, with_duration=with_duration)
    stats["targets"] = len(rows)
    for r in rows:
        name = (r.name_zh or "").strip()
        if not name:
            continue
        cat, indoor, rain_ok, floor = _classify(name, r.category)
        if with_duration and cat is None:
            floor = None  # 类别都定不了，地板值不硬塞
        written = _write_row(
            factory,
            r.id,
            indoor=indoor,
            rain_ok=rain_ok,
            category=cat,
            floor=floor if with_duration else None,
        )
        for col in written:
            stats["filled"][col] = stats["filled"].get(col, 0) + 1
        if written and len(stats["samples"]) < 10:
            stats["samples"].append(
                {
                    "name": name,
                    "city": r.city,
                    "cols": written,
                    "category": cat,
                    "indoor": indoor,
                    "rain_ok": rain_ok,
                    "floor": floor,
                }
            )
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int) -> None:
    rows = select_targets(session_factory, limit=limit, with_duration=False)
    print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=True))
    for r in rows[:5]:
        cat, indoor, rain_ok, _ = _classify((r.name_zh or "").strip(), r.category)
        print(
            json.dumps(
                {
                    "name": r.name_zh,
                    "old_cat": r.category,
                    "new_cat": cat,
                    "indoor": indoor,
                    "rain_ok": rain_ok,
                },
                ensure_ascii=True,
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Category heuristics enrichment")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument(
        "--with-duration",
        action="store_true",
        help="also fill duration floors (run LAST)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    factory = get_session_factory()
    if args.dry_run:
        dry_run(factory, limit=args.limit)
        return 0
    stats = enrich(factory, limit=args.limit, with_duration=args.with_duration)
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
