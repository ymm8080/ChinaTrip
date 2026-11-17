# -*- coding: utf-8 -*-
import json, os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])

from app.db import get_session_factory
from app.services.pg_state import PgTripItemService

ITIN = "it-f84ab5be"
DEV = "dev-hs4e9vhk"
ACCT = "914542970@qq.com"

with eng.connect() as c:
    names = {
        r[0]
        for r in c.execute(text(
            "select ii.name from itinerary_items ii"
            " join itineraries i on i.id = ii.itinerary_id"
            " where i.plan->>'itinerary_id' = :r and ii.snapshot_id is null"
        ), {"r": ITIN})
    }
print("plan sites:", sorted(names))

factory = get_session_factory()
svc = PgTripItemService(factory)

# backup before heal
with factory() as s:
    rows = s.execute(
        text("select payload from trip_items where owner_device_id=:d and deletion_flag=false"),
        {"d": DEV},
    ).all()
backup = [dict(r[0]) if not isinstance(r[0], str) else json.loads(r[0]) for r in rows]
os.makedirs(r"D:\CHINATRIP\DESIGN\backup", exist_ok=True)
out = r"D:\CHINATRIP\DESIGN\backup\trip_items_orphan_adopt_backup_2026-11-14.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(backup, f, ensure_ascii=False, indent=1)
print("backup rows:", len(backup), "->", out)

n = svc.commit_orphan_drafts(
    ITIN, owner_device_id=DEV, owner_account_id=ACCT, match_names=names,
)
print("adopted:", n)
d = svc.dedupe_itinerary_rows(ITIN, actor="orphan-adopt-heal")
print("deduped:", d)
