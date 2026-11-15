import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    for r in c.execute(text("select name, owner_device_id, owner_account_id, draft_session_id, deletion_flag, itinerary_ref from trip_items where owner_device_id='probe-uidkey-1114'")):
        print("DB:", r)
