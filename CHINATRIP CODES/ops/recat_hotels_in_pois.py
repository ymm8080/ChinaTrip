# -*- coding: utf-8 -*-
"""pois 表住宿行归类（2026-10-31，可重跑；口径 v2 用户修正）。

背景：chinatravel 餐厅错标行经 move_rest_to_pois 搬入 pois 时，GLM
kind=hotel 的 subtype（酒店/民宿/自然风光…）经旧 normalize_category
归一成 None，再被 classify 裸「园」/「山」名称 hint 误归 park/nature/
attraction，污染景点池（单日 ~1500 行）。

处置（2026-10-31 用户拍板）：住宿行**不隐藏**——category='hotel' 后
保持 active 入库可查；误标是「类别」问题不是「上下架」问题。
幂等：名称命中住宿词（poi_classify._ACCOMMODATION_HINTS 同源 +
悦榕庄/美宿）或已属 hotel 的行 → category='hotel'，status 不动。

move_rest_to_pois 跑完后再执行一次收尾：
    python ops/recat_hotels_in_pois.py
"""

from __future__ import annotations

import io
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.db import get_session_factory
from app.services.poi_classify import _ACCOMMODATION_HINTS

TOKENS = (*_ACCOMMODATION_HINTS, "悦榕庄", "美宿")
PAT = "|".join(TOKENS)
LOG = Path(__file__).parent / "recat_hotels_in_pois_executed.log"


def main() -> int:
    factory = get_session_factory()
    with factory() as s:
        rows = s.execute(
            text(
                "select id, city, name_zh, category, status, source from pois "
                "where name_zh is not null and category <> 'hotel'"
            )
        ).fetchall()
        hits = [r for r in rows if re.search(PAT, r.name_zh)]
        for r in hits:
            s.execute(
                text("update pois set category='hotel', updated_at=NOW() where id=:i"),
                {"i": r.id},
            )
        s.commit()
        left = s.execute(
            text(
                "select category, status, count(*) from pois "
                "where name_zh ~ :pat or category='hotel' group by 1, 2 order by 1, 2"
            ),
            {"pat": PAT},
        ).fetchall()
    print(f"scanned={len(rows)} recategorized={len(hits)}")
    print(
        "hotel-ish/hotel rows remaining by category/status:",
        [tuple(r) for r in left],
    )
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(
            f"{datetime.now().isoformat(timespec='seconds')} scanned={len(rows)} "
            f"hit={len(hits)} remaining={[tuple(r) for r in left]}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
