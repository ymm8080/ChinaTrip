import sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from app.services.trip_items import TripItemService
svc = TripItemService()
try:
    row = svc.create("测试点", source="paste", itinerary_id="it-x", owner_device_id="d1", city="杭州", note="n", raw_command="测试点", must_visit=True)
    print("created:", row["name"], row["id"])
    print("groups:", [i["name"] for i in svc.list_groups()["wishlist"]])
except Exception as e:
    print("ERROR", type(e).__name__, e)
