# -*- coding: utf-8 -*-
"""退役行 tags 并集回收（DEDUP 去重轮的历史治愈）。

去重轮退役败者行时，旧语义只在 keeper 空 tags 时搬，带标败者的
intl/ta/lp/xiaohongshu/4a 等实体级标会丢。本脚本全库扫 retired 行，
按 别名+同城 找到合并目标 keeper，把缺失的 tags 并集补进去，幂等。
找不到 keeper 的列出来留台账，不乱写。
"""

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_session_factory  # noqa: E402
from app.models import Poi  # noqa: E402


def main() -> None:
    factory = get_session_factory()
    healed = orphan = 0
    with factory() as s:
        losers = (
            s.query(Poi)
            .filter(Poi.status == "retired", Poi.tags.isnot(None))
            .order_by(Poi.updated_at)
            .all()
        )
        for lo in losers:
            tags = [t for t in (lo.tags or []) if t]
            if not tags:
                continue
            cands = (
                s.query(Poi)
                .filter(
                    Poi.status == "active",
                    Poi.city == lo.city,
                    Poi.name_aliases.op("?")(lo.name_zh),
                )
                .all()
            )
            if not cands:
                orphan += 1
                print(
                    f"ORPHAN [{lo.source}] {lo.name_zh} tags={tags} (无别名指向 keeper)"
                )
                continue
            if len(cands) > 1:
                names = [c.name_zh for c in cands]
                print(
                    f"WARN [{lo.source}] {lo.name_zh} "
                    f"命中 {len(cands)} 个 keeper，取第一个: {names}"
                )
            k = cands[0]
            added = [t for t in tags if t not in (k.tags or [])]
            if added:
                k.tags = list(k.tags or []) + added
                healed += 1
                print(f"HEAL [{k.name_zh}] tags += {added} <- retired {lo.name_zh}")
        s.commit()
    print(f"\nhealed={healed} orphans={orphan}")


if __name__ == "__main__":
    main()
