# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\alembic\versions\w12_0036_user_id_keying.py"
raw = io.open(p, encoding="utf-8", newline="").read()
lines = raw.splitlines()
out = []
i = 0
while i < len(lines):
    l = lines[i]
    if l.strip() == "op.add_column(" and i + 3 < len(lines):
        nxt1, nxt2, nxt3 = lines[i+1].strip(), lines[i+2].strip(), lines[i+3].strip()
        if (
            nxt1 in ('"itinerary_items",', '"action_handoffs",')
            and nxt2 == "op.add_column("
        ):
            # duplicated wrapper from the device-column removal: drop these two lines
            i += 2
            continue
    out.append(l)
    i += 1
io.open(p, "w", encoding="utf-8", newline="").write("\r\n".join(out) + "\r\n")
print("fixed")
