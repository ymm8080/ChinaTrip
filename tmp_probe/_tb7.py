# -*- coding: utf-8 -*-
import io, re
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
lines = io.open(p, encoding="utf-8", newline=None).read().replace(chr(13), "").split("\n")
cnt = 0
for i, ln in enumerate(lines):
    s = ln.strip()
    if s.startswith("run(agent.message(") and s.endswith(")"):
        indent = ln[: len(ln) - len(ln.lstrip())]
        # 丢弃返回值的调用：改成接住会话副本（message 深拷贝，改动在副本上）
        lines[i] = indent + "session, _, _ = " + s
        cnt += 1
io.open(p, "w", encoding="utf-8", newline="\r\n").write("\n".join(lines))
print("rewired", cnt)
