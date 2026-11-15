# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_planned_rows_sync.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = NL.join([
'    notes, unresolved = asyncio.run(',
'        agent.sync_wishes_to_trip_items(session, [], user_texts=None)',
'    )',
'    assert notes == [] and unresolved == []',
'    groups = svc.list_groups("it-test")',
])
new = NL.join([
'    notes, unresolved = asyncio.run(',
'        agent.sync_wishes_to_trip_items(session, [], user_texts=None)',
'    )',
'    assert notes == [] and unresolved == []',
'    # 2026-11-15：规划回合不再写心愿行——对账/翻牌挪到保存行程时',
'    agent.sync_trip_rows(session, at_save=True)',
'    groups = svc.list_groups("it-test")',
])
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("fixed")
