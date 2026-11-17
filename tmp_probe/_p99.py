# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_wish_draft_lifecycle.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = NL.join([
'    unwanted = [r for r in svc.list_groups()["unwanted"] if r["name"] == "迪士尼"]',
'    assert unwanted, "排除项应物化成 EXCLUSION 行（unwanted 分区）"',
])
new = NL.join([
'    excluded = [',
'        r',
'        for r in svc.list_groups()["wishlist"]',
'        if r["name"] == "迪士尼" and r.get("exclusion_flag")',
'    ]',
'    assert excluded, "排除项应物化成 EXCLUSION 行（心愿单栏 + 排除标记）"',
])
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("test fixed")
