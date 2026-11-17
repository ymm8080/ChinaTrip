# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''    assert session.state == "ready"
    return agent, session, svc, llm
''', '''    assert session.state == "ready"
    _SESSIONS.append((agent, session))  # 供 _wish_row 做保存物化
    return agent, session, svc, llm
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
