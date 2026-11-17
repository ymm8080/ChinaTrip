import sys
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
from app.services.poi_details import PoiDetailStore
from app.db import get_session_factory
store = PoiDetailStore(get_session_factory())
texts = [
    "I WANT TO GO TO ZHUJIAZUI ON DEC.02.  LEAVE HOTEL ON 11AM, PLS ARRANGE",
    "SHANGHAI 2DAY'S TRIP INCLUDING THE BUND, SHANGHAI MUSEUM, ORITAL TOWER, CURISE, YUGARDEN ZHUJIAZUI",
    "goto zhujiazui",
    "2 days in shanghai, museums and food",
    "SHANGHAI 2 DAYS, THE BUND AND YUGARDEN",
]
for t in texts:
    whole = store.match_text_names(None, t)
    sh = store.match_text_names("上海", t)
    print("TEXT:", t[:60])
    print("  whole-lib:", [(r["name"], r["city"]) for r in whole])
    print("  上海-scoped:", [(r["name"], r["city"]) for r in sh])
