"""pois 用户可选二级标签回填：category/tags/review_tags/name/source/bvt
→ user_family / user_groups。

DESIGN user_tag_two_level_2026-11-10 §一：7 一级 × 25 二级受控词表。
映射唯一来源 app/services/poi_tag_selector.classify_poi（规则级联，
review 粗词碰撞消解见该模块 docstring）；本任务只填空——已有
user_family 的行不动，未命中/服务类（hotel/food/transport/category=None）
留空不猜。原始 category/tags/review_tags 列永不改写。幂等可重跑。

用法：
    python -m app.jobs.backfill_poi_user_tags [--limit 100000] [--dry-run]
"""

import argparse
import logging

from sqlalchemy import text

from app.db import get_session_factory
from app.models import Poi
from app.services.poi_tag_selector import (
    GROUPS_BY_FAMILY,
    _EXCLUDED_CATEGORIES,
    classify_poi,
)

logger = logging.getLogger(__name__)

_SELECT_COLS = (
    Poi.id,
    Poi.category,
    Poi.tags,
    Poi.review_tags,
    Poi.name_zh,
    Poi.source,
    Poi.best_visit_time,
)


def select_targets(session_factory, *, limit: int) -> list[tuple]:
    """全量选待填行（user_family IS NULL，fill-empty-only）。

    只取推导所需列（location 等几何/长文本列不加载）；user_groups 与
    user_family 同写同空，单看 user_family 即完整口径。
    """
    with session_factory() as session:
        return (
            session.query(*_SELECT_COLS)
            .filter(Poi.user_family.is_(None))
            .order_by(Poi.id)
            .limit(limit)
            .all()
        )


def run(*, limit: int = 100000, dry_run: bool = False) -> int:
    factory = get_session_factory()
    rows = select_targets(factory, limit=limit)
    written = 0
    excluded = 0
    unmatched = 0
    for pid, cat, tags, rv, name, source, bvt in rows:
        family, _groups = classify_poi(cat, tags, rv, name, source, bvt)
        c0 = str(cat or "").strip().lower()
        if family is None:
            if c0 in _EXCLUDED_CATEGORIES or not c0:
                excluded += 1  # 服务类行/无类目行：选择器口径排除
            else:
                unmatched += 1  # 未命中不猜，留给词表扩充
            continue
        if dry_run:
            written += 1
            continue
        with factory() as session:
            db_row = session.get(Poi, pid)
            if db_row is None or db_row.user_family is not None:
                continue  # 写前复查（只填空语义）
            # 写前重算：读-写间隙 category/tags/review_tags 可能被回源链改写
            fam2, grp2 = classify_poi(
                db_row.category,
                db_row.tags,
                db_row.review_tags,
                db_row.name_zh,
                db_row.source,
                db_row.best_visit_time,
            )
            if fam2 is None:
                continue
            db_row.user_family = fam2
            db_row.user_groups = grp2 or None
            session.commit()
            written += 1
    logger.info(
        "poi user_tags backfill: written=%d selected=%d excluded=%d unmatched=%d",
        written,
        len(rows),
        excluded,
        unmatched,
    )
    _print_distribution(factory, dry_run=dry_run, written=written, unmatched=unmatched)
    return written


def _print_distribution(
    factory, *, dry_run: bool, written: int, unmatched: int
) -> None:
    """跑完打印分布：有标签行数、各一级/二级标签计数、排除数。

    dry_run 打印内存计数（不写库）；实跑以库内聚合为准。
    """
    if dry_run:
        print(
            f"[dry-run 分布] 本次可写={written} 服务类排除见 run 日志 "
            f"unmatched={unmatched}（未写库，库内计数不变）"
        )
        return
    with factory() as session:
        total = session.execute(text("SELECT count(*) FROM pois")).scalar()
        tagged = session.execute(
            text("SELECT count(*) FROM pois WHERE user_family IS NOT NULL")
        ).scalar()
        svc = session.execute(
            text(
                "SELECT count(*) FROM pois "
                "WHERE lower(category) IN ('hotel', 'food', 'transport')"
            )
        ).scalar()
        nocat = session.execute(
            text("SELECT count(*) FROM pois WHERE category IS NULL")
        ).scalar()
        fam_rows = session.execute(
            text(
                "SELECT user_family, count(*) FROM pois "
                "WHERE user_family IS NOT NULL GROUP BY user_family"
            )
        ).all()
        grp_rows = session.execute(
            text(
                "SELECT grp, count(*) FROM pois, "
                "jsonb_array_elements_text(user_groups) AS grp "
                "WHERE user_groups IS NOT NULL GROUP BY grp"
            )
        ).all()
    fam_counts = {f: int(n) for f, n in fam_rows}
    grp_counts = {t: int(n) for t, n in grp_rows}
    print(
        f"[分布] total={total} 有标签={tagged} "
        f"hotel/food/transport 排除={svc} category=None 排除={nocat} "
        f"未命中留空={total - tagged - svc - nocat}"
    )
    for fam, groups in GROUPS_BY_FAMILY.items():
        print(f"  {fam}\t{fam_counts.get(fam, 0)}")
        for g in groups:
            print(f"    {g}\t{grp_counts.get(g, 0)}")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
