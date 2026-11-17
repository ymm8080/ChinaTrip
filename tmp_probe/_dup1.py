# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print("=== 颐和园 行（未删） ===")
    for r in c.execute(text("""
        select id, name, city, status, day, itinerary_ref, owner_device_id, owner_account_id,
               source, draft_session_id, deletion_flag, created_at, updated_at,
               payload->>'id' as payload_id
          from trip_items
         where name like '%颐和园%' and deletion_flag = false
         order by created_at
    """)):
        print(r)
