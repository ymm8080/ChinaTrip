import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    for r in c.execute(text("select name, owner_device_id, status, itinerary_ref, draft_session_id, deletion_flag, deleted_by from trip_items where name='住上海花园饭店' order by created_at desc limit 5")):
        print(r)
