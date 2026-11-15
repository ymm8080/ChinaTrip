# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\alembic\versions\w12_0035_trip_item_drafts.py"
t = io.open(p, encoding="utf-8", newline="").read()
bad = 'VIEW_PLAIN = VIEW_WITH_DRAFT_FILTER.replace(\r\n    "        WHERE t.draft_session_id IS NULL\r\n", ""\r\n)\r\n'
good = 'VIEW_PLAIN = VIEW_WITH_DRAFT_FILTER.replace(\r\n    "        WHERE t.draft_session_id IS NULL\\n", ""\r\n)\r\n'
assert t.count(bad) == 1, t.count(bad)
t = t.replace(bad, good, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("fixed migration")
