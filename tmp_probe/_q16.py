import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print('--- itinerary_items for it-ee39df46')
    for r in c.execute(text("select name, owner_account_id from itinerary_items ii where ii.itinerary_id in (select id from itineraries where plan->>'itinerary_id'='it-ee39df46') limit 6")):
        print(r)
    print('--- trip header')
    for r in c.execute(text("select owner_device_id, owner_account_id from itineraries where plan->>'itinerary_id'='it-ee39df46'")):
        print(r)
