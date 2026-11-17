import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
DEV = "probe-stageonly-1115"
with eng.connect() as c:
    n = c.execute(text("select count(*) from trip_items where owner_device_id=:d or owner_account_id like 'probe_stage_%'"), {"d": DEV}).scalar()
    print("DB rows saved during planning phase (must be 0):", n)
