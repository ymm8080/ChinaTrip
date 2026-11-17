# -*- coding: utf-8 -*-
import json, os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
from app.db import get_session_factory
from app.services.pg_state import PgTripItemService

# 1) backup live rows bound to itineraries that have duplicate wish keys
with eng.connect() as c:
    dup_refs = [
        r[0]
        for r in c.execute(text("""
            select itinerary_ref from trip_items
            where deletion_flag = false and itinerary_ref is not null
            group by itinerary_ref, owner_device_id, name
            having count(*) > 1
        """))
    ]
print("itineraries with duplicate wish rows:", dup_refs)
backup = []
factory = get_session_factory()
svc = PgTripItemService(factory)
if dup_refs:
    with factory() as s:
        rows = s.execute(
            text("select payload from trip_items where deletion_flag = false and itinerary_ref = any(:refs)"),
            {"refs": dup_refs},
        ).all()
    backup = [dict(r[0]) if not isinstance(r[0], str) else json.loads(r[0]) for r in rows]
    os.makedirs(r"D:\CHINATRIP\DESIGN\backup", exist_ok=True)
    out = r"D:\CHINATRIP\DESIGN\backup\trip_items_dup_cleanup_backup_2026-11-14.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)
    print("backup rows:", len(backup), "->", out)

# 2) dedupe each
total = 0
for ref in dup_refs:
    n = svc.dedupe_itinerary_rows(ref, actor="wish-dedupe-cleanup")
    total += n
    print("deduped", ref, "->", n)
print("TOTAL soft-deleted duplicates:", total)
