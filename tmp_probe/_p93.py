# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_wish_draft_lifecycle.py"
t = io.open(p, encoding="utf-8", newline=None).read()
t = t.replace('    agent.sync_wishes_to_trip_items(session, ["豫园"])\n', '    asyncio.run(agent.sync_wishes_to_trip_items(session, ["豫园"]))\n')
if "import asyncio\n" not in t:
    t = t.replace("import json\n", "import asyncio\nimport json\n", 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("await fixed")
