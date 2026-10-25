"""POI 富化·类别启发式（indoor/rain_ok + duration 地板值，零联网）。

词典与判定逻辑在 app/services/poi_classify.py（与 poi_seed 插入即
分类共用）。三段：
  1. 有 category 的行：类别→indoor/rain_ok 直接映射；
  2. category 为空的行：name_zh 关键词保守分类，高置信才落 category
     （category 无 source 列，落错的代价=分类元数据不准，可接受；
     置信不足的一律不碰）；
  3. duration 地板值（--with-duration 才启用）：类别/名称→分钟下限，
     duration_source='heuristic'。

2026-10-25 拍板（用户指令）：地板是"规划下限"不是事实主张，真值源
（ctrip/qunar/llm_web）可升级覆盖 heuristic 值——本作业不再是
"必须最后跑"的占坑者，新行插入（poi_seed）即打地板，本作业做存量
清扫（poi_daily 链尾）。

用法：
    python -m app.jobs.enrich_heuristics [--limit 5000] [--with-duration] [--dry-run]
"""

import argparse
import json
import sys

from sqlalchemy import or_

from app.db import get_session_factory
from app.models import Poi
from app.services.poi_classify import classify as _classify

_DEFAULT_LIMIT = 5000


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
