"""restaurants 照片马蜂窝收割入库（真浏览器会话收割 JSON → 只填空写库）.

输入：_tmp_probe_web/mfw_harvest_restaurants_*.json（entries: search/poiId/
title/urls）。规则：
  * fill-empty-only：仅 status='active' AND photos IS NULL 行写入；
  * name 精确匹配（search 字段即库内 name_zh，收割时已过分店闸/简繁归一）；
  * url 收口复用 poi_photos.normalize_photos（http(s)、去重、≤8 条）；
  * photos_source='mafengwo'，photos_fetched_at 尝试即落戳（与全链同口径）。

用法（CHINATRIP CODES 目录下）：
    python ops/ingest_restaurant_photos_mafengwo.py path/to/harvest.json [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # ops/ → 仓库根

import psycopg  # noqa: E402

from app.services.poi_photos import normalize_photos  # noqa: E402

DB = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest mafengwo restaurant photos")
    parser.add_argument("harvest_json", type=str)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    doc = json.loads(Path(args.harvest_json).read_text(encoding="utf-8"))
    entries = doc.get("entries") or []
    filled = skipped = missing = empty = 0

    conn = psycopg.connect(DB)
    cur = conn.cursor()
    for e in entries:
        name = (e.get("search") or "").strip()
        photos = normalize_photos([{"title": "", "url": u} for u in e.get("urls") or []])
        if not photos:
            empty += 1
            continue
        cur.execute(
            "SELECT id, photos IS NULL FROM restaurants "
            "WHERE status='active' AND name_zh = %s",
            (name,),
        )
        rows = cur.fetchall()
        if not rows:
            missing += 1
            print("MISS", name)
            continue
        row_id, is_null = rows[0]
        if not is_null:
            skipped += 1
            continue
        if args.dry_run:
            filled += 1
            print("WOULD FILL", name, len(photos))
            continue
        cur.execute(
            "UPDATE restaurants SET photos = %s::jsonb, photos_source = 'mafengwo', "
            "photos_fetched_at = %s WHERE id = %s AND photos IS NULL",
            (json.dumps(photos, ensure_ascii=False), datetime.now(), row_id),
        )
        if cur.rowcount:
            filled += 1
            print("FILLED", name, len(photos))
    if not args.dry_run:
        conn.commit()
    conn.close()
    print(
        json.dumps(
            {
                "entries": len(entries),
                "filled": filled,
                "already_had_photos": skipped,
                "no_db_row": missing,
                "no_photos": empty,
                "dry_run": args.dry_run,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
