import sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.stdout.reconfigure(encoding="utf-8")
from app.services import access_services
for name in ("慕田峪长城","八达岭长城"):
    s = access_services.best_service("北京", name)
    if s:
        print(name, "|", s.service_name, "| first", s.first_departure(), "last", s.last_departure(), "ride", s.ride_minutes, "fare", s.fare_text(), "return_last", s.return_last)
    else:
        print(name, "none")
