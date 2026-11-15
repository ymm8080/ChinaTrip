import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print('--- saved itinerary business ids')
    saved = {r[0] for r in c.execute(text("select plan->>'itinerary_id' from itineraries"))}
    print(sorted(saved))
    print('--- trip refs')
    refs = {}
    for r in c.execute(text("select itinerary_ref, count(*) from trip_items where deletion_flag=false group by 1")):
        refs[r[0]] = r[1]
    print('refs:', refs)
    print('--- refs NOT in saved')
    for k, v in refs.items():
        if k not in saved:
            print(' orphan/unsaved:', k, v)
    print('--- saved refs w/o rows')
    for k in saved:
        if k not in refs:
            print(' saved no rows:', k)
