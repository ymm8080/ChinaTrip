# -*- coding: utf-8 -*-
import io, re
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_planned_rows_sync.py"
t = io.open(p, encoding="utf-8", newline=None).read()
t = t.replace(", at_save=True)", ")")
# 把 at_save 加为关键字参数到被测函数调用（此前误加进 _session 工厂）
t = re.sub(r"agent\._sync_planned_rows\(_session\(agent, plan, at_save=True\)\)", r"agent._sync_planned_rows(_session(agent, plan), at_save=True)", t)
t = re.sub(r"agent\._sync_planned_rows\(_session\(agent, plan, at_save=True\)\)", r"agent._sync_planned_rows(_session(agent, plan), at_save=True)", t)
t = re.sub(r"agent\._sync_planned_rows\(session, at_save=True\)", r"agent._sync_planned_rows(session, at_save=True)", t)
t = re.sub(r"agent2\._sync_planned_rows\(session2, at_save=True\)", r"agent2._sync_planned_rows(session2, at_save=True)", t)
t = re.sub(r"agent\._sync_wish_rows\(session, at_save=True\)", r"agent._sync_wish_rows(session, at_save=True)", t)
t = re.sub(r"agent\.sync_trip_rows\(session, at_save=True\)", r"agent.sync_trip_rows(session, at_save=True)", t)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("fixed")
