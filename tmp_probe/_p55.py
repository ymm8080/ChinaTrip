# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = "from app.api.itineraries import _trip_items_service, get_store\n"
new = "from app.api.itineraries import _account_from_auth, _trip_items_service, get_store\n"
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
