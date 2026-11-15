import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    for r in c.execute(text("select name, status, source, itinerary_ref, draft_session_id, deletion_flag, created_by, created_at from trip_items where owner_device_id='probe-stageonly-1115' or owner_account_id like 'probe_stage_%'")):
        print(r)
