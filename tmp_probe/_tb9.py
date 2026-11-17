# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''    _save(agent, session)
    assert svc.list_groups(iid)["wishlist"][0]["name"] == "博物馆"
''', '''    _save(agent, session)
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [r["name"] for r in rows] == ["博物馆"]
''')
sub('''    _save(agent, session)
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["city"]) for i in wish] == [("博物馆人文", "上海")]
''', '''    _save(agent, session)
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [(r["name"], r["city"]) for r in rows] == [("博物馆人文", "上海")]
''')
sub('''    _save(agent, session)
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["city"]) for i in wish] == [("博物馆人文", None)]
''', '''    _save(agent, session)
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [(r["name"], r["city"]) for r in rows] == [("博物馆人文", None)]
''')
sub('''    _save(agent, session)
    assert svc.list_groups()["wishlist"][0]["city"] == "杭州"
''', '''    _save(agent, session)
    rows = [r for zone in svc.list_groups().values() for r in zone if r["name"] == "灵隐寺"]
    assert rows and rows[0]["city"] == "杭州"
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
