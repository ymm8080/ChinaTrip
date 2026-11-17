import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print("--- trip_items rows created in last 3 hours")
    for r in c.execute(text("""
        select name, owner_device_id, owner_account_id, status, day, itinerary_ref,
               draft_session_id, deletion_flag, source, created_at
        from trip_items
        where created_at > now() - interval '3 hours'
        order by created_at desc limit 30
    """)):
        print(r)
    print("--- itineraries created in last 3 hours")
    for r in c.execute(text("""
        select plan->>'itinerary_id' iid, owner_device_id, owner_account_id, created_at, updated_at, is_deleted
        from itineraries where created_at > now() - interval '3 hours'
        order by created_at desc limit 10
    """)):
        print(r)
