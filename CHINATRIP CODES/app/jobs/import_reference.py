"""参考数据导入作业（海外侧，DESIGN language_dual_system §5.4）。

消费 export_reference 的 NDJSON+manifest：校验 SHA256 → 按自然键幂等
upsert（CN 业务列覆盖、本地 _en 非空保留、墓碑传播）→ poi_hours 按
本地 poi_id 重链（先清后插）。dry-run 只校验不写库。

用法（海外侧）：
    python -m app.jobs.import_reference --dir data/reference_export/<批次>
        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

from sqlalchemy import func

from app.models import Poi, PoiHour, Restaurant
from app.services.coords import make_point
from app.services.reference_sync import parse_export, plan_import, verify_manifest


def _existing_lookup(session, model, source: str, source_poi_id: str):
    return (
        session.query(model)
        .filter(model.source == source, model.source_poi_id == source_poi_id)
        .first()
    )


def _apply_geo(updates: dict) -> dict:
    """lon/lat 元组 → geography WKTElement（写库适配）。"""
    if "location" in updates and isinstance(updates["location"], tuple):
        updates["location"] = make_point(*updates["location"])
    if "wgs84_location" in updates and isinstance(updates["wgs84_location"], tuple):
        updates["wgs84_location"] = make_point(*updates["wgs84_location"])
    return updates


def apply_records(session, records: list[dict], *, dry_run: bool) -> dict:
    stats = {
        "insert": 0,
        "update": 0,
        "skip": 0,
        "hours_relinked": 0,
        "errors": 0,
    }
    model_of = {"pois": Poi, "restaurants": Restaurant}
    for rec in records:
        model = model_of.get(rec.get("table"))
        if model is None:
            stats["skip"] += 1
            continue
        try:
            existing = _existing_lookup(
                session, model, rec.get("source"), rec.get("source_poi_id")
            )
            action, updates = plan_import(rec, existing)
            if action == "skip":
                stats["skip"] += 1
                continue
            if dry_run:
                stats[action] += 1
                continue
            updates = _apply_geo(updates)
            if action == "insert":
                # ORM 主键无默认生成器（CN 摄入侧总是显式赋 id）——导入侧
                # 必须自己生成，否则 NotNullViolation（本地 INTL 实测抓到）
                updates.setdefault("id", uuid.uuid4())
                row = model(**updates)
                session.add(row)
                session.flush()  # 拿 id 供 hours 重链
            else:
                row = existing
                for col, val in updates.items():
                    setattr(row, col, val)
                session.flush()
            # hours 重链：先清后插（CN 全量为准）
            if rec["table"] == "pois":
                session.query(PoiHour).filter(PoiHour.poi_id == row.id).delete()
                for h in rec.get("hours") or []:
                    session.add(
                        PoiHour(
                            poi_id=row.id,
                            rule_type=h.get("rule_type") or "windows",
                            payload=h.get("payload") or {},
                        )
                    )
                    stats["hours_relinked"] += 1
            stats[action] += 1
        except Exception:
            stats["errors"] += 1
            session.rollback()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="参考数据导入（海外侧幂等 upsert）")
    parser.add_argument("--dir", required=True, help="导出批次目录")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    nd_path = os.path.join(args.dir, "reference.ndjson")
    mf_path = os.path.join(args.dir, "manifest.json")
    if not (os.path.exists(nd_path) and os.path.exists(mf_path)):
        print(json.dumps({"error": "missing reference.ndjson / manifest.json"}))
        return 1
    with open(nd_path, encoding="utf-8") as f:
        ndjson = f.read()
    with open(mf_path, encoding="utf-8") as f:
        manifest = json.load(f)
    reason = verify_manifest(ndjson, manifest)
    if reason:
        print(json.dumps({"error": reason}))
        return 1
    records = parse_export(ndjson)

    from app.db import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        session.query(func.count(Poi.id)).scalar()  # ping
        stats = apply_records(session, records, dry_run=args.dry_run)
        if not args.dry_run:
            session.commit()
    stats["manifest"] = {
        "exported_at": manifest.get("exported_at"),
        "counts": manifest.get("counts"),
        "sha256_ok": True,
    }
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
