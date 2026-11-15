# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''            if isinstance(item, VisitItem)
            and item.start_time is not None
            and item.poi_id
            and ((item.category or "") != "food" or _is_show_banquet_item(item))
            and (item.category or "") != "hotel"
'''
new = '''            if isinstance(item, VisitItem)
            and item.start_time is not None
            and ((item.category or "") != "food" or _is_show_banquet_item(item))
            and (item.category or "") != "hotel"
'''
c = t.count(old)
assert c == 1, c
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("planned relaxed")
