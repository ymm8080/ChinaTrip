# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\alembic\versions\w12_0036_user_id_keying.py"
t = io.open(p, encoding="utf-8", newline=None).read()
pairs = [
    ("        UPDATE itinerary_items it\n               owner_account_id = i.owner_account_id\n",
     "        UPDATE itinerary_items it\n           SET owner_account_id = i.owner_account_id\n"),
    ("        UPDATE action_handoffs h\n               owner_account_id = i.owner_account_id\n",
     "        UPDATE action_handoffs h\n           SET owner_account_id = i.owner_account_id\n"),
    ("    # 头表 owner_* 是权威）。\n", "    # 头表 owner_account_id 是权威）。\n"),
]
for old, new in pairs:
    c = t.count(old)
    assert c == 1, (c, old[:60])
    t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("migration fixed")
