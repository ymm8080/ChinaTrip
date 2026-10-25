"""参考数据导出作业（CN 侧，DESIGN language_dual_system §5.4）。

pois/restaurants/poi_hours → NDJSON + manifest，输出目录
data/reference_export/<exported_at>/。海外侧用 import_reference 消费。
weather 不在链内（海外侧 Open-Meteo 自取，见设计文档 v1.2 修订）。

用法：
    python -m app.jobs.export_reference [--out data/reference_export]
        [--since "2026-10-25 00:00:00"]   # 增量水位（默认全量）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from sqlalchemy import func, or_

from app.models import Poi, PoiHour, Restaurant
from app.services.reference_sync import (
    POI_EXPORT_COLS,
    RESTAURANT_EXPORT_COLS,
    row_to_record,
    serialize_export,
)


def _lonlat(wkt: str | None) -> tuple[float, float] | None:
    if not wkt:
        return None
    parts = wkt.replace("POINT(", "").replace(")", "").split()
    return (float(parts[0]), float(parts[1])) if len(parts) == 2 else None


def collect(session, *, since: str | None = None) -> list[dict]:
    records: list[dict] = []
    for model, table, cols in (
        (Poi, "pois", POI_EXPORT_COLS),
        (Restaurant, "restaurants", RESTAURANT_EXPORT_COLS),
    ):
        q = session.query(
            model,
            func.ST_AsText(model.location).label("loc_txt"),
            func.ST_AsText(model.wgs84_location).label("wgs_txt"),
        ).filter(
            or_(model.status.is_(None), model.status == "active")
            | (model.status == "inactive")
        )  # 全量（含墓碑）
        if since:
            q = q.filter(model.updated_at >= datetime.fromisoformat(since))
        hours_by_poi: dict = {}
        if table == "pois":
            hq = session.query(PoiHour).all()
            for h in hq:
                hours_by_poi.setdefault(h.poi_id, []).append(
                    {"rule_type": h.rule_type, "payload": h.payload}
                )
        for row, loc_txt, wgs_txt in q.all():
            records.append(
                row_to_record(
                    table,
                    row,
                    loc=_lonlat(loc_txt),
                    wgs84=_lonlat(wgs_txt),
                    hours=hours_by_poi.get(row.id),
                )
            )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="参考数据导出（CN→海外单向同步）")
    parser.add_argument("--out", default="data/reference_export")
    parser.add_argument("--since", default=None, help="增量水位 ISO datetime")
    args = parser.parse_args(argv)

    from app.db import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        session.query(Poi.id).first()  # ping
        records = collect(session, since=args.since)
    exported_at = datetime.now().strftime("%Y-%m-%d %H%M%S")
    ndjson, manifest = serialize_export(records, exported_at=exported_at)
    manifest["since"] = args.since
    import os

    out_dir = os.path.join(args.out, exported_at.replace(" ", "_").replace(":", ""))
    os.makedirs(out_dir, exist_ok=True)
    nd_path = os.path.join(out_dir, "reference.ndjson")
    mf_path = os.path.join(out_dir, "manifest.json")
    with open(nd_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(ndjson)
    with open(mf_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(json.dumps({"out_dir": out_dir, **manifest}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
