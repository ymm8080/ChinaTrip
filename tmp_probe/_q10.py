import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print("--- remaining duplicates (must be 0)")
    for r in c.execute(text("""
        select name, owner_device_id, count(*) n from trip_items
        where deletion_flag = false and itinerary_ref is not null
        group by itinerary_ref, owner_device_id, name having count(*) > 1
    """)):
        print(r)
    print("--- sample kept rows")
    for r in c.execute(text("""
        select name, owner_device_id, status, day, deletion_flag, deleted_by
        from trip_items where itinerary_ref='it-63b6ca44' and deletion_flag=false
        order by name
    """)):
        print(r)
    print("--- flagged count today")
    print(c.execute(text("select count(*) from trip_items where deletion_flag=true and deleted_by='wish-dedupe-cleanup'")).scalar())
