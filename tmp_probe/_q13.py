import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    for tbl in ("trip_items", "itinerary_items", "action_handoffs"):
        cols = [r[0] for r in c.execute(text(
            "select column_name from information_schema.columns"
            " where table_name=:t and column_name like 'owner%'"), {"t": tbl})]
        print(tbl, cols)
    print('backfilled trip_items with account:',
        c.execute(text("select count(*) from trip_items where owner_account_id is not null and deletion_flag=false")).scalar())
    print('backfilled itinerary_items:',
        c.execute(text("select count(*) from itinerary_items where owner_account_id is not null")).scalar())
