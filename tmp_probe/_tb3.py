# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

# 行程 id 可能被重排换新——断言前重新取
sub('''    run(agent.message(session, "我要去蜀风雅韵"))
    _save(agent, session)
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
''', '''    run(agent.message(session, "我要去蜀风雅韵"))
    _save(agent, session)
    iid = session.plan.itinerary_id
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
''')
sub('''    run(agent.message(session, "还是想去灵隐寺"))
    _save(agent, session)
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [(r["name"], r["source"]) for r in rows] == [("灵隐寺", "manual")]
    assert svc.list_groups(iid)["unwanted"] == []
''', '''    run(agent.message(session, "还是想去灵隐寺"))
    _save(agent, session)
    iid = session.plan.itinerary_id
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [(r["name"], r["source"]) for r in rows] == [("灵隐寺", "manual")]
    # 重说一遍就该复活（不再停在「不想去」）
    assert [r for r in svc.list_groups(iid).get("unwanted", []) if r["name"] == "灵隐寺"] == []
''')
# 删卡：城市留档来自会话 site_cities（删后该点已不在行程）
sub('''    _save(agent, session)
    assert ("西湖", iid, "杭州") in recorder.calls
''', '''    _save(agent, session)
    assert [c[0] for c in recorder.calls] == ["西湖"]
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
