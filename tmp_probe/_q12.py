import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print("--- live rows by device/ref (visible after draft filter)")
    for r in c.execute(text("""
        select owner_device_id, itinerary_ref, count(*) n, count(distinct name) names
        from trip_items
        where deletion_flag = false and draft_session_id is null
        group by owner_device_id, itinerary_ref order by n desc limit 15
    """)):
        print(r)
    print("--- duplicates among VISIBLE rows (must be empty)")
    for r in c.execute(text("""
        select owner_device_id, itinerary_ref, name, count(*) n
        from trip_items
        where deletion_flag = false and draft_session_id is null
        group by owner_device_id, itinerary_ref, name having count(*) > 1
    """)):
        print(r)
    print("--- dev-hs4e9vhk rows")
    for r in c.execute(text("""
        select name, status, itinerary_ref, draft_session_id, deletion_flag, deleted_by, created_at
        from trip_items where owner_device_id='dev-hs4e9vhk' order by created_at
    """)):
        print(r)
