import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    for r in c.execute(text("""
        select name, status, exclusion_flag, itinerary_ref, source, owner_account_id,
               created_by, (payload->>'exclusion_flag') as p_excl, note
          from trip_items
         where name like '%颐和园%' and deletion_flag = false
         order by created_at
    """)):
        print(dict(r._mapping) if hasattr(r, "_mapping") else r)
