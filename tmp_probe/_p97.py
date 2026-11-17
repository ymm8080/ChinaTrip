# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''                    if target is None and item.poi_id and _name_dup(name, item.name):
                        target = item
'''
new = '''                    # 名字命中即可（无 poi_id 的用户点名条目也要能对上）
                    if target is None and _name_dup(name, item.name):
                        target = item
'''
c = t.count(old)
assert c == 2, c
# 只替换 materialize_wish_rows 里那处（第二处是 _sync_wish_rows 的同款——也一并放宽无妨，
# 但 _sync_wish_rows 只在保存时跑，行为一致即可）
t = t.replace(old, new, 2)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("both relaxed")
