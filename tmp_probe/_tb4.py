# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

# 专名被排进行程：新口径下这条不改心愿单（行由保存对账落，见 _sync_planned_rows）
sub('''    run(agent.message(session, "我要去蜀风雅韵"))
    _save(agent, session)
    iid = session.plan.itinerary_id
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [(r["name"], r["source"]) for r in rows] == [("蜀风雅韵", "chat")]
''', '''    run(agent.message(session, "我要去蜀风雅韵"))
    # 2026-11-15 拍板：规划期不写心愿行——专名被排进行程，行由保存对账
    # （_sync_planned_rows）落；这里只确认没在规划期偷偷建行。
    assert svc.list_groups() == {} or not any(svc.list_groups().values())
    _save(agent, session)
    iid = session.plan.itinerary_id
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert any(r["name"] == "蜀风雅韵" for r in rows)
''')

# 「重说一遍复活」：行是预置的用户行（manual），复活走 update 路径
sub('''    run(agent.message(session, "还是想去灵隐寺"))
    _save(agent, session)
    iid = session.plan.itinerary_id
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [(r["name"], r["source"]) for r in rows] == [("灵隐寺", "manual")]
    # 重说一遍就该复活（不再停在「不想去」）
    assert [r for r in svc.list_groups(iid).get("unwanted", []) if r["name"] == "灵隐寺"] == []
''', '''    run(agent.message(session, "还是想去灵隐寺"))
    _save(agent, session)
    iid = session.plan.itinerary_id
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [r["name"] for r in rows].count("灵隐寺") == 1
    assert [(r["name"], r["source"]) for r in rows] == [("灵隐寺", "manual")]
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
