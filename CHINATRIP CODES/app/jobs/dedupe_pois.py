"""POI 同地名去重（一条有效记录，其余 inactive）。

用户拍板 2026-11-16：**「we should set one record valid with all necessary
information, another record to be inactive」**——`pois` 里同一个地方常有
多行（渠道骨架 / 名录行 / 行政区行），规划按名字命中哪行全看运气。

    # 看某个地方会怎么合并（只算不写）
    python -m app.jobs.dedupe_pois --city 上海 --name 朱家角 --dry-run

    # 真合并（默认把信息最全的 active 行当幸存者）
    python -m app.jobs.dedupe_pois --city 上海 --name 朱家角 --apply

    # 指定幸存行（source:source_poi_id 或 UUID）
    python -m app.jobs.dedupe_pois --city 上海 --name 朱家角 --keep 4a:4a_0064 --apply

    # 扫全城（默认 dry-run；--apply 才写库）
    python -m app.jobs.dedupe_pois --city 上海 --scan --limit 200 --apply

合并语义见 ``app.services.poi_ingest.merge_place``：幸存行只填空，退役行的
名字/别名并入幸存行 ``name_aliases``，退役行置 ``status='inactive'``（不删
行）。写库前把受影响行快照落 ``DESIGN/backup/poi_dedupe_<date>.json``。
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.db import get_session_factory
from app.models import Poi
from app.services.poi_ingest import merge_place
from app.services.poi_names import place_core

_BACKUP_DIR = Path(__file__).resolve().parents[3] / "DESIGN" / "backup"


def _resolve_keep(keep: str, factory) -> str | None:
    """``--keep`` 支持 UUID 或 ``source:source_poi_id``（目录源口味更自然）。"""
    if ":" not in keep:
        return keep
    source, source_poi_id = keep.split(":", 1)
    with factory() as session:
        row = (
            session.query(Poi.id)
            .filter(Poi.source == source, Poi.source_poi_id == source_poi_id)
            .first()
        )
    return str(row[0]) if row is not None else None


def _scan_candidates(city: str | None, limit: int) -> list[str]:
    """同城同内核、多于一条 active 行的地名（扫全城用）。"""
    sql = (
        "SELECT name_zh, city, count(*) AS n FROM pois"
        " WHERE (status IS NULL OR status = 'active')"
    )
    params: dict = {}
    if city:
        sql += " AND city = ANY(:cities)"
        params["cities"] = [city, f"{city}市"]
    sql += " GROUP BY name_zh, city HAVING count(*) > 1"
    factory = get_session_factory()
    with factory() as session:
        rows = session.execute(text(sql), params).all()
    buckets: dict[tuple[str, str], list[str]] = {}
    for name, row_city, _n in rows:
        core = place_core(name)
        if core:
            buckets.setdefault((str(row_city), core), []).append(str(name))
    out: list[str] = []
    for (_row_city, _core), names in buckets.items():
        out.append(names[0])
    return out[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POI 同地名去重（一条有效，其余 inactive）"
    )
    parser.add_argument("--city", default=None, help="城市（如 上海）")
    parser.add_argument("--name", default=None, help="地点名/内核（如 朱家角）")
    parser.add_argument(
        "--keep", default=None, help="指定幸存行（source:source_poi_id 或 UUID）"
    )
    parser.add_argument("--scan", action="store_true", help="扫全城同内核多行地点")
    parser.add_argument("--limit", type=int, default=200, help="扫描上限")
    parser.add_argument("--apply", action="store_true", help="真写库（缺省只算不写）")
    parser.add_argument(
        "--dry-run", action="store_true", help="只算不写（缺省行为，显式开关为可读性）"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not args.name and not args.scan:
        parser.error("需要 --name 或 --scan")

    names = [args.name] if args.name else _scan_candidates(args.city, args.limit)
    factory = get_session_factory()
    receipts: list[dict] = []
    merged = 0
    for name in names:
        result = merge_place(
            name,
            args.city,
            factory=factory,
            dry_run=not args.apply,
            keep_id=_resolve_keep(args.keep, factory) if args.keep else None,
        )
        if result is None:
            print(f"· {name}: 无同地名重复行")
            continue
        merged += 1
        payload = result.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.apply:
            receipts.append({"query": name, "city": args.city, **payload})
    if not args.apply:
        print(f"\n（dry-run）可合并 {merged} 处；加 --apply 写库")
        return
    if receipts:
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        path = _BACKUP_DIR / f"poi_dedupe_{date.today().isoformat()}.json"
        path.write_text(
            json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已写库 {merged} 处；快照 {path}")


if __name__ == "__main__":
    main()
