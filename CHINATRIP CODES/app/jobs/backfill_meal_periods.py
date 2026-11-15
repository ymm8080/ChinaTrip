"""restaurants 餐段回填：opening_hours + cuisine_group → meal_periods。

DESIGN user_tag_two_level_2026-11-10 §三：推导唯一来源
app/services/meal_periods.infer_meal_periods（纯函数，解析不了的
opening_hours 返回 [] 不猜——回填把 [] 落库标记「已处理无餐段」，
下游 _allowed_slots_for 对空列表走原营业时间推断，行为不变）。
本任务只填空——meal_periods IS NULL 且 opening_hours 非空的行才进
选择；写前复查（行级重取 + 重算，读-写间隙 hours 可能被回源链补上）
保证幂等可重跑。纯本地计算，零外部 API。

用法：
    python -m app.jobs.backfill_meal_periods [--limit 20000] [--dry-run]
"""

import argparse
import logging

from app.db import get_session_factory
from app.models import Restaurant
from app.services.meal_periods import infer_meal_periods

logger = logging.getLogger(__name__)


def select_targets(session_factory, *, limit: int) -> list[Restaurant]:
    with session_factory() as session:
        return (
            session.query(Restaurant)
            .filter(
                Restaurant.meal_periods.is_(None),
                Restaurant.opening_hours.isnot(None),
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
        periods = infer_meal_periods(row.opening_hours, row.cuisine_group)
        if dry_run:
            logger.info(
                "dry %s %s/%s: %s",
                row.id,
                row.opening_hours,
                row.cuisine_group,
                periods,
            )
            written += 1
            continue
        with factory() as session:
            db_row = session.get(Restaurant, row.id)
            if db_row is None or db_row.meal_periods is not None:
                continue  # 写前复查（只填空语义）
            # 写前重算：读-写间隙 opening_hours 可能被回源链补上
            periods2 = infer_meal_periods(db_row.opening_hours, db_row.cuisine_group)
            db_row.meal_periods = periods2
            session.commit()
            written += 1
    logger.info("meal_periods backfill: written=%d selected=%d", written, len(rows))
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
