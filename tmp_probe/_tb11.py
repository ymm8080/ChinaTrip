# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''    row = next(r for r in rows if r["name"] == "看变脸表演")
    assert (row["source"], row["note"]) == ("chat", "来自聊天")
'''.replace(chr(13), "")
new = '''    row = next(r for r in rows if r["name"] == "看变脸表演")
    assert row["source"] == "chat"
    assert row["note"].startswith("来自聊天")  # 已安排会追加「（第N天 时刻）」
'''.replace(chr(13), "")
assert t.count(old) == 1
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t.replace(old, new))
print("ok")
