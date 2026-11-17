"""pois.review_tags 词表迁移：36 个携程细词 → 12 个粗标签（存量重刷）。

DESIGN user_tag_two_level_2026-11-10 §五。与 cuisine 粗化不同，本任务
是**重刷**而非只填空——粗化改的是写进 JSONB 的词汇本身，已有行的细词
会原样映射替换（未知词透传保留），review_tags_source 不动。幂等可重跑
（粗词再过一遍映射不变）。

用法：
    python -m app.jobs.backfill_review_tags_coarse [--limit 20000] [--dry-run]
"""

import argparse
import logging

from app.db import get_session_factory
from app.models import Poi
from app.services.review_tag_coarse import coarse_tags

logger = logging.getLogger(__name__)


def select_targets(session_factory, *, limit: int) -> list[Poi]:
    with session_factory() as session:
        return (
            session.query(Poi)
            .filter(Poi.review_tags.isnot(None))
            .order_by(Poi.id)
            .limit(limit)
            .all()
        )


def run(*, limit: int = 20000, dry_run: bool = False) -> int:
    factory = get_session_factory()
    rows = select_targets(factory, limit=limit)
    written = 0
    for row in rows:
        mapped = coarse_tags(row.review_tags)
        if mapped == list(row.review_tags):
            continue  # 已是粗词（或纯未知词），不动
        if dry_run:
            logger.info("dry %s: %s -> %s", row.id, row.review_tags, mapped)
            written += 1
            continue
        with factory() as session:
            db_row = session.get(Poi, row.id)
            if db_row is None or db_row.review_tags is None:
                continue
            mapped2 = coarse_tags(db_row.review_tags)
            if mapped2 == list(db_row.review_tags):
                continue  # 读-写间隙已被别的轮次刷过
            db_row.review_tags = mapped2
            session.commit()
            written += 1
    logger.info("review_tags coarse: written=%d selected=%d", written, len(rows))
    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
