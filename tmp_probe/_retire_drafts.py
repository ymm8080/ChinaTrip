import os, sys, json
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    n = c.execute(text("select count(*) from trip_items where draft_session_id is not null and deletion_flag=false")).scalar()
    print("legacy draft rows to retire:", n)
    rows = c.execute(text("select payload from trip_items where draft_session_id is not null and deletion_flag=false")).all()
backup = [dict(r[0]) if not isinstance(r[0], str) else json.loads(r[0]) for r in rows]
import os as _os
out = r"D:\CHINATRIP\DESIGN\backup\trip_items_legacy_drafts_retire_2026-11-15.json"
_os.makedirs(r"D:\CHINATRIP\DESIGN\backup", exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(backup, f, ensure_ascii=False, indent=1)
print("backup ->", out, len(backup))
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
with eng.begin() as c:
    c.execute(text("""
        update trip_items
           set deletion_flag = true,
               deletion_date = :dd,
               deletion_time = :tt,
               deleted_by = 'legacy-draft-retire',
               payload = coalesce(payload, '{}'::jsonb)
                 || jsonb_build_object('deletion_flag', true, 'deletion_date', :ddi, 'deletion_time', :tt, 'deleted_by', 'legacy-draft-retire')
         where draft_session_id is not null and deletion_flag = false
    """), {"dd": now.date(), "tt": now.strftime("%H:%M:%S"), "ddi": now.date().isoformat()})
with eng.connect() as c:
    print("remaining drafts:", c.execute(text("select count(*) from trip_items where draft_session_id is not null and deletion_flag=false")).scalar())
