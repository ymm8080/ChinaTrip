"""poi_stats 夜聚合作业（DESIGN §3.4 D2，2026-10-25）。

trip_items 每天产生的行为（wishlist=wish、scheduled=plan、unwanted
=dislike）+ 反馈计数（👍/打卡/链接提及）→ 合并落 poi_stats。**这是
竞品拿不到的自有热度源**：全量重建（量小幂等），未匹配到 pois 行的
键跳过并计数（骨架未回源时常见，不报错）。

用法：
    python -m app.jobs.aggregate_poi_stats
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from app.models import Poi, PoiStat

logger = logging.getLogger(__name__)


def aggregate_poi_stats(
    trip_items,
    feedback,
    *,
    session_factory=None,
) -> dict:
    """全量重建计数；返回统计。memory-only（无 PG）也返回合并结果。"""
    counts: dict[tuple[str, str], dict] = {}

    def bucket(name: str, city: str | None) -> dict:
        key = (
            (name or "").strip(),
            (city or "").strip().removesuffix("市"),
        )
        return counts.setdefault(
            key,
            {
                "wish_count": 0,
                "plan_count": 0,
                "visit_count": 0,
                "dislike_count": 0,
                "thumbs_up": 0,
                "xhs_mentions": 0,
            },
        )

    groups = trip_items.list_groups()
    for item in groups.get("wishlist") or []:
        b = bucket(item.get("name") or "", item.get("city"))
        b["wish_count"] += 1
    for item in groups.get("scheduled") or []:
        b = bucket(item.get("name") or "", item.get("city"))
        b["plan_count"] += 1
    for item in groups.get("booked") or []:
        b = bucket(item.get("name") or "", item.get("city"))
        b["plan_count"] += 1  # 已订也是被排期
    for item in groups.get("unwanted") or []:
        b = bucket(item.get("name") or "", item.get("city"))
        b["dislike_count"] += 1

    # 反馈计数（vote/visit/mention 的内存态）
    for key, c in feedback.export_counters().items():
        name, city = key
        b = bucket(name, city)
        for field in ("visit_count", "thumbs_up", "xhs_mentions"):
            b[field] += c.get(field, 0)

    stats = {"keys": len(counts), "pg_written": 0, "pg_unmatched": 0}
    if session_factory is not None:
        now = datetime.now(timezone.utc)
        try:
            with session_factory() as session:
                for (name, city), c in counts.items():
                    if not name:
                        continue
                    row = (
                        session.query(Poi)
                        .filter(
                            Poi.name_zh == name,
                            Poi.city.in_({city, f"{city}市"}),
                        )
                        .first()
                    )
                    if row is None:
                        stats["pg_unmatched"] += 1
                        continue
                    stat = session.get(PoiStat, row.id)
                    if stat is None:
                        stat = PoiStat(poi_id=row.id)
                        session.add(stat)
                    for field in (
                        "wish_count",
                        "plan_count",
                        "visit_count",
                        "dislike_count",
                        "thumbs_up",
                        "xhs_mentions",
                    ):
                        setattr(stat, field, c[field])
                    stat.updated_at = now
                    stats["pg_written"] += 1
                session.commit()
        except Exception:
            logger.warning("aggregate_poi_stats: db write failed", exc_info=True)
            stats["db_error"] = True
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="poi_stats 夜聚合（全量重建）")
    parser.parse_args(argv)

    from app.services.poi_feedback import get_poi_feedback_store
    from app.services.trip_items import TripItemService

    trip_items = TripItemService()  # 进程态（作业独立进程=当前快照）
    feedback = get_poi_feedback_store()
    session_factory = None
    try:
        from app.db import get_session_factory

        session_factory = get_session_factory()
    except Exception:
        logger.warning(
            "aggregate_poi_stats: session_factory unavailable, "
            "aggregating in-memory data only (partial data)",
            exc_info=True,
        )
        session_factory = None
    stats = aggregate_poi_stats(trip_items, feedback, session_factory=session_factory)
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
