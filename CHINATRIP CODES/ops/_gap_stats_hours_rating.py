"""盘点 opening_hours / rating 缺口（active 口径，按 source 与城市）。临时脚本。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_

from app.db import get_session_factory
from app.models import Poi


def main() -> None:
    with get_session_factory()() as session:
        active = session.query(Poi).filter(Poi.status == "active")
        total = active.count()
        hours_null = active.filter(Poi.opening_hours.is_(None)).count()
        rating_null = active.filter(Poi.rating.is_(None)).count()
        both = active.filter(Poi.opening_hours.is_(None), Poi.rating.is_(None)).count()

        hours_by_src = dict(
            active.filter(Poi.opening_hours.is_(None))
            .with_entities(Poi.source, __import__("sqlalchemy").func.count())
            .group_by(Poi.source)
            .all()
        )
        rating_by_src = dict(
            active.filter(Poi.rating.is_(None))
            .with_entities(Poi.source, __import__("sqlalchemy").func.count())
            .group_by(Poi.source)
            .all()
        )
        hours_filled_src = dict(
            active.filter(Poi.opening_hours.isnot(None))
            .with_entities(Poi.hours_source, __import__("sqlalchemy").func.count())
            .group_by(Poi.hours_source)
            .all()
        )
        rating_filled_src = dict(
            active.filter(Poi.rating.isnot(None))
            .with_entities(Poi.rating_source, __import__("sqlalchemy").func.count())
            .group_by(Poi.rating_source)
            .all()
        )
        # hours 缺口按城市（前 25）
        hours_city = Counter(
            session.query(Poi.city)
            .filter(Poi.status == "active", Poi.opening_hours.is_(None))
            .all()
            and [
                (r[0] or "?")
                for r in active.filter(Poi.opening_hours.is_(None))
                .with_entities(Poi.city)
                .all()
            ]
        )
        # amap 源里 hours/rating 还空的（enrich_amap_detail 的直接靶子）
        amap_hours = active.filter(
            Poi.source == "amap",
            Poi.source_poi_id.isnot(None),
            Poi.opening_hours.is_(None),
        ).count()
        amap_rating = active.filter(
            Poi.source == "amap",
            Poi.source_poi_id.isnot(None),
            Poi.rating.is_(None),
        ).count()
        amap_any = active.filter(
            Poi.source == "amap",
            Poi.source_poi_id.isnot(None),
            or_(
                Poi.opening_hours.is_(None),
                Poi.rating.is_(None),
                Poi.phone.is_(None),
                Poi.business_area.is_(None),
                Poi.photos.is_(None),
            ),
        ).count()

    print(
        json.dumps(
            {
                "active_total": total,
                "hours_null": hours_null,
                "rating_null": rating_null,
                "both_null": both,
                "hours_null_by_source": hours_by_src,
                "rating_null_by_source": rating_by_src,
                "hours_filled_by_source": hours_filled_src,
                "rating_filled_by_source": rating_filled_src,
                "hours_null_top_cities": hours_city.most_common(25),
                "amap_rows_hours_null": amap_hours,
                "amap_rows_rating_null": amap_rating,
                "amap_rows_any_target_null": amap_any,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
