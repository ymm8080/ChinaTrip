# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''    _save(agent, session)
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["source"], i["note"]) for i in wish] == [
        ("看变脸表演", "chat", "来自聊天")
    ]
'''.replace(chr(13), "")
new = '''    _save(agent, session)
    # 保存对账按核心词认到正主 → 这一行进已排期（不再是心愿单态）
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    row = next(r for r in rows if r["name"] == "看变脸表演")
    assert (row["source"], row["note"]) == ("chat", "来自聊天")
'''.replace(chr(13), "")
assert t.count(old) == 1
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t.replace(old, new))
print("test ok")
