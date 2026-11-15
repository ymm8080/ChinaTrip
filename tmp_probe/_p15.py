# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
t = io.open(p, encoding="utf-8", newline="").read()
old = '                    {"ref": itinerary_id, "sid": session_id or "", "uid": uid},\r\n'
new = '                    {"ref": itinerary_id, "sid": session_id or ""},\r\n'
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
