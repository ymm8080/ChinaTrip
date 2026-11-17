"""restaurants 二级标签回填：cuisine 原值 → cuisine_family/cuisine_group。

DESIGN user_tag_two_level_2026-11-10 §二：用户选择器的两级标签。
映射唯一来源 app/services/cuisine_taxonomy.classify_cuisine（规则级联，
575 个原值实测零漏网）；本任务只填空——已有 family/group 的行不动，
原值 cuisine 列永不改写。幂等可重跑。

用法：
    python -m app.jobs.backfill_cuisine_group [--limit 20000] [--dry-run]
"""

import argparse
import logging

from app.db import get_session_factory
from app.models import Restaurant
from app.services.cuisine_taxonomy import classify_cuisine

logger = logging.getLogger(__name__)


def select_targets(session_factory, *, limit: int) -> list[Restaurant]:
    with session_factory() as session:
        return (
            session.query(Restaurant)
            .filter(
                Restaurant.status == "active",
                Restaurant.cuisine.isnot(None),
                Restaurant.cuisine_family.is_(None),
            )
            .order_by(Restaurant.id)
            .limit(limit)
            .all()
        )


def run(*, limit: int = 20000, dry_run: bool = False) -> int:
    factory = get_session_factory()
    rows = select_targets(factory, limit=limit)
    written = 0
    for row in rows:
        family, group = classify_cuisine(row.cuisine)
        if family is None:
            continue  # 未命中不猜，留给词表扩充
        if dry_run:
            logger.info("dry %s %s: %s/%s", row.id, row.cuisine, family, group)
            written += 1
            continue
        with factory() as session:
            db_row = session.get(Restaurant, row.id)
            if db_row is None or db_row.cuisine_family is not None:
                continue  # 写前复查（只填空语义）
            # 写前重算：读-写间隙原值可能被回源链改写
            fam2, grp2 = classify_cuisine(db_row.cuisine)
            if fam2 is None:
                continue
            db_row.cuisine_family = fam2
            db_row.cuisine_group = grp2
            session.commit()
            written += 1
    logger.info("cuisine_group backfill: written=%d selected=%d", written, len(rows))
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
