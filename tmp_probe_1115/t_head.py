import sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.stdout.reconfigure(encoding="utf-8")
from app.services.poi_access import head_chain_minutes
from app.services.itinerary.models import VisitItem, GeoPoint
v = VisitItem(item_id="mt", name="慕田峪长城", city="北京", day=1, poi_id="ct_北京_8", duration_minutes=180, location=GeoPoint(lon=116.55980232499265, lat=40.426661851582196))
print("head chain 慕田峪:", head_chain_minutes(v))
