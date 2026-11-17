# -*- coding: utf-8 -*-
import io, re
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_planned_rows_sync.py"
t = io.open(p, encoding="utf-8", newline=None).read()
t = t.replace("agent._sync_planned_rows(", "agent._sync_planned_rows_at_save_alias(")
# restore with at_save kw
t = t.replace("agent._sync_planned_rows_at_save_alias(", "agent._sync_planned_rows(")
t = re.sub(r"agent\._sync_planned_rows\(([^)\n]+)\)", r"agent._sync_planned_rows(\1, at_save=True)", t)
t = re.sub(r"agent\._sync_wish_rows\(([^)\n]+)\)", r"agent._sync_wish_rows(\1, at_save=True)", t)
t = re.sub(r"agent\.sync_trip_rows\(([^)\n]+)\)", r"agent.sync_trip_rows(\1, at_save=True)", t)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("tests gated")
