import sys
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
from app.services.poi_details import PoiDetailStore
from app.db import get_session_factory
BRIEF = ("SHANGHAI 2DAY'S TRIP INCLUDING THE BUND, SHANGHAI MUSEUM, "
         "ORITAL TOWER, CURISE, YUGARDEN ZHUJIAZUI")
store = PoiDetailStore(get_session_factory())
print("db_available:", store._db_available())
for i in range(3):
    rows = store.match_text_names("上海", BRIEF)
    print(i, [(r["name"], r.get("name_en")) for r in rows])
