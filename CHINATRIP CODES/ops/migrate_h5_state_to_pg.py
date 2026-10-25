"""一次性搬迁：SQLite h5_state.db → PG（行程 + 心愿单），幂等可重跑.

任务书 2026-10-25（B 期「行程保存即入库」）：把 H5 状态库里 320 条行程 +
11 条心愿单搬进 PG（alembic 0015 已加列）。读 SQLite 两表 payload，经
PgItineraryStore.put / PgTripItemService.import_item 写穿——按 PK upsert，
重复执行只更新不堆行。SQLite 文件原样保留为备份。

前置：alembic upgrade head（0015）+ PG 可达。用法（任意 cwd）：

    .venv\\Scripts\\python.exe ops\\migrate_h5_state_to_pg.py [--db data/h5_state.db]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_session_factory  # noqa: E402
from app.models import Itinerary, TripItem  # noqa: E402
from app.services.itinerary_store import ItineraryRecord  # noqa: E402
from app.services.pg_state import PgItineraryStore, PgTripItemService  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/h5_state.db", help="SQLite 状态库路径")
    args = parser.parse_args(argv)

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    factory = get_session_factory()
    store = PgItineraryStore(factory)
    items = PgTripItemService(factory)

    stats = {"itineraries": 0, "itineraries_skipped": 0, "trip_items": 0}
    for (payload,) in con.execute("SELECT payload FROM itineraries"):
        try:
            record = ItineraryRecord.model_validate_json(payload)
        except Exception as exc:
            print(f"skip itinerary (bad payload): {exc}")
            stats["itineraries_skipped"] += 1
            continue
        store.put(record)
        stats["itineraries"] += 1

    for (payload,) in con.execute("SELECT payload FROM trip_items"):
        if items.import_item(json.loads(payload)):
            stats["trip_items"] += 1

    with factory() as session:
        pg_itins = session.query(Itinerary).count()
        pg_items = session.query(TripItem).count()

    print(
        f"migrated: {stats['itineraries']} itineraries"
        f" ({stats['itineraries_skipped']} skipped),"
        f" {stats['trip_items']} trip items | PG now:"
        f" itineraries={pg_itins}, trip_items={pg_items}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
