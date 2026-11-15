# -*- coding: utf-8 -*-
import io, re
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_planned_rows_sync.py"
t = io.open(p, encoding="utf-8", newline=None).read()
t = re.sub(r"(agent\d?\._sync_planned_rows\()(session\d)\)", r"\1\2, at_save=True)", t)
t = re.sub(r"(agent\d?\._sync_wish_rows\()(session\d)\)", r"\1\2, at_save=True)", t)
t = re.sub(r"(agent\d?\.sync_trip_rows\()(session\d)\)", r"\1\2, at_save=True)", t)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("done")
