# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_trip_items.py"
t = io.open(p, encoding="utf-8", newline="").read()
old = "# 草稿标记，看板/接口不返回；点「保存行程」提交后才可见。\r\n\r\ndef test_purge_itinerary"
new = "# 草稿标记，看板/接口不返回；点「保存行程」提交后才可见。\r\n\r\n\r\ndef test_purge_itinerary"
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
