# -*- coding: utf-8 -*-
import io
for path in (
    r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py",
    r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py",
):
    t = io.open(path, encoding="utf-8", newline=None).read()
    old = "def mark_excluded(self, name, *, itinerary_id=None, city=None, draft_session_id=None):"
    new = "def mark_excluded(self, name, *, itinerary_id=None, city=None, draft_session_id=None, owner_account_id=None):"
    c = t.count(old)
    print(path.split(chr(92))[-1], "count:", c)
    if c:
        t = t.replace(old, new)
        io.open(path, "w", encoding="utf-8", newline="\r\n").write(t)
print("stubs ok")
