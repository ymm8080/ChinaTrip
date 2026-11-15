import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
with eng.begin() as c:
    c.execute(text("""
        update trip_items
           set deletion_flag = true,
               deletion_date = :dd,
               deletion_time = cast(:tt as time),
               deleted_by = 'legacy-draft-retire',
               payload = coalesce(payload, '{}'::jsonb)
                 || jsonb_build_object('deletion_flag', true, 'deletion_date', cast(:dd as text), 'deletion_time', cast(:tt as text), 'deleted_by', 'legacy-draft-retire')
         where draft_session_id is not null and deletion_flag = false
    """), {"dd": now.date(), "tt": now.strftime("%H:%M:%S")})
with eng.connect() as c:
    print("remaining drafts:", c.execute(text("select count(*) from trip_items where draft_session_id is not null and deletion_flag=false")).scalar())
    print("live visible rows:", c.execute(text("select count(*) from trip_items where draft_session_id is null and deletion_flag=false")).scalar())
