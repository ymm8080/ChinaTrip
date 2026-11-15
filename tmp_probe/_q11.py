import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    for r in c.execute(text("""
        select name, status, day, itinerary_ref, draft_session_id, deletion_flag, deleted_by, created_at
        from trip_items where owner_device_id='probe-final-1114' order by created_at desc limit 12
    """)):
        print(r)
    print('--- saved itineraries containing it-63b6ca44?')
    print(c.execute(text("select count(*) from itineraries where plan->>'itinerary_id'='it-63b6ca44'")).scalar())
