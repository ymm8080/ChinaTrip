"""剧院类 POI 无场次退役（2026-11-10 用户拍板「剧院有 SHOW 留着，没有
SHOW 安排只是地名 SET TO INACTIVE」）。

判据：
- 候选：active 且 name_zh 命中 剧院|剧场|戏院|梨园|曲艺|评弹|川剧|相声|
  话剧|歌剧|音乐厅|livehouse（大小写不敏感）。
- 假阳性排除：名含 酒店/宾馆/客栈/地铁，或 category='hotel'/'nature'
  （酒店挂牌行与古梨园类景区行不是剧院）。
- 场次关联：全库 active 且 source='show' 的演出行 intro 嵌场馆名——
  双向包含匹配（剥 ·分店/(分店) 缀），任一命中即"有 SHOW"保留。
- 退役：mark_status(status="inactive") 现行惯例（poi_seed.py），
  快照表 pois_theater_sweep_bak_20261110（CTAS，可回滚）。
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text

from app.db import get_session_factory
from app.models import Poi
from app.services.poi_seed import mark_status

logger = logging.getLogger("theater_retire")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

BAK_TABLE = "pois_theater_sweep_bak_20261110"
THEATER_RE = re.compile(
    r"剧院|剧场|戏院|梨园|曲艺|评弹|川剧|相声|话剧|歌剧|音乐厅|livehouse", re.I
)
EXCLUDE_NAME_RE = re.compile(r"酒店|宾馆|客栈|地铁")
EXCLUDE_CATS = {"hotel", "nature"}
BRANCH_STRIP_RE = re.compile(r"[·・\-\s]*[(（][^)）]*[)）]|[·・].*$")


def _core(name: str) -> str:
    """剥分店/括注缀，双向包含匹配用。"""
    return BRANCH_STRIP_RE.sub("", name).strip()


def main() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        candidates = (
            session.query(Poi)
            .filter(Poi.status == "active", Poi.name_zh.op("~*")(THEATER_RE.pattern))
            .all()
        )
        show_intros = [
            str(r[0] or "")
            for r in session.query(Poi.intro)
            .filter(Poi.status == "active", Poi.source == "show")
            .all()
        ]

    kept, excluded, retired, failed = [], [], [], []
    for poi in candidates:
        name = str(poi.name_zh or "")
        cat = str(poi.category or "").strip().lower()
        if EXCLUDE_NAME_RE.search(name) or cat in EXCLUDE_CATS:
            excluded.append({"id": poi.id, "name": name, "category": cat})
            continue
        core = _core(name)
        has_show = any(
            (core and core in intro) or (name and name in intro)
            for intro in show_intros
        )
        if has_show:
            kept.append({"id": poi.id, "name": name})
            continue
        ok = mark_status(
            session_factory, Poi, poi.source, poi.source_poi_id, "inactive"
        )
        rec = {"id": poi.id, "name": name, "city": poi.city, "source": poi.source}
        (retired if ok else failed).append(rec)
        logger.info(
            "theater_retire: %s %s (%s/%s)",
            "INACTIVE" if ok else "FAILED",
            name,
            poi.city,
            poi.source,
        )

    ids = [r["id"] for r in retired] + [r["id"] for r in kept]
    if ids:
        with session_factory() as session:
            exists = session.execute(
                text("SELECT 1 FROM pg_tables WHERE tablename = :t"),
                {"t": BAK_TABLE},
            ).first()
            if exists:
                logger.warning("theater_retire: 快照表 %s 已存在，跳过快照", BAK_TABLE)
            else:
                quoted = ",".join(f"'{i}'" for i in ids)
                session.execute(
                    text(
                        f"CREATE TABLE {BAK_TABLE} AS "
                        f"SELECT * FROM pois WHERE id IN ({quoted})"
                    )
                )
                session.commit()
                logger.info("theater_retire: 快照 %s (%d 行)", BAK_TABLE, len(ids))

    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "kept_has_show": kept,
                "excluded_false_positive": excluded,
                "retired": retired,
                "failed": failed,
                "bak_table": BAK_TABLE,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
