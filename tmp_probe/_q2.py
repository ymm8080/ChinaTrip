import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print('--- itineraries cols')
    for r in c.execute(text("select column_name, data_type from information_schema.columns where table_name='itineraries' order by ordinal_position")):
        print(r)
    print('--- itineraries rows')
    for r in c.execute(text("select * from itineraries limit 12")):
        print(tuple(r)[:6])
    print('--- trip_items status/count')
    for r in c.execute(text("select status, deletion_flag, count(*) from trip_items group by 1,2 order by 3 desc")):
        print(r)
    print('--- trip_items sample')
    for r in c.execute(text("select id, name, status, source, itinerary_ref, itinerary_id, owner_device_id, created_by, arranged, deletion_flag, created_at from trip_items order by created_at desc limit 12")):
        print(r)
