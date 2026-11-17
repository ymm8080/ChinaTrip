import sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.stdout.reconfigure(encoding="utf-8")
from app.db import get_session_factory
from app.services.access_service_store import AccessServiceStore
from app.services import access_services as A
A.configure_store(AccessServiceStore(get_session_factory()))
for name in ("慕田峪长城","八达岭长城"):
    print("==", name, "services:", len(A.services_for("北京", name)))
    for s in A.services_for("北京", name):
        print("  ", s.service_name, "|", s.ride_minutes, "|", A.fmt_minutes(s.first_departure()), A.fmt_minutes(s.last_departure()), "|", s.fare_note, "|", s.official_url)
    b = A.best_service("北京", name)
    print("  best:", b.service_name if b else None)
