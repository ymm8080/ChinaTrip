import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print('--- probe device rows')
    for r in c.execute(text("select name, status, itinerary_ref, draft_session_id, deletion_flag, deletion_date, deleted_by from trip_items where owner_device_id='probe-wishdel-1114' order by created_at")):
        print(r)
    print('--- view for probe device names')
    for r in c.execute(text("select wish_name from wish_items where created_by='probe-wishdel-1114'")):
        print(r)
