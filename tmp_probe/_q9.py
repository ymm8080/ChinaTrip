import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print("--- duplicate names among live rows (any status)")
    for r in c.execute(text("""
        select name, owner_device_id, count(*) n,
               string_agg(distinct coalesce(itinerary_ref,'-'), ' | ') refs,
               string_agg(distinct coalesce(draft_session_id,'-'), ' | ') drafts
        from trip_items
        where deletion_flag = false
        group by name, owner_device_id
        having count(*) > 1
        order by n desc, name
        limit 20
    """)):
        print(r)
    print("--- scheduled rows detail (latest 20)")
    for r in c.execute(text("""
        select name, owner_device_id, status, itinerary_ref, day, draft_session_id, source, created_at
        from trip_items
        where deletion_flag = false and status = 'scheduled'
        order by created_at desc limit 20
    """)):
        print(r)
