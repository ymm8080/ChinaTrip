import sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from app.services.agent import plan as P
for name in ["蜀风雅韵", "看变脸表演", "灵隐寺"]:
    print(name,
          "service_meta=", P._is_service_meta_wish(name),
          "trip_brief=", P._is_trip_brief_wish(name),
          "cat=", P._category_search_keyword(name),
          "key=", P._wish_key(name))
