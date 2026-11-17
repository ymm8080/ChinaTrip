# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

# 删卡：规划期只记会话（选择闸即时生效），保存时打 EXCLUSION
sub('''    assert "西湖" not in {v.name for v in all_visits(session)}
    assert recorder.calls == [("西湖", iid, "杭州")]
''', '''    assert "西湖" not in {v.name for v in all_visits(session)}
    # 2026-11-15 拍板：规划期不写库——排除项记会话，保存时打 EXCLUSION
    assert recorder.calls == []
    assert "西湖" in session.avoid_sites
    _save(agent, session)
    assert ("西湖", iid, "杭州") in recorder.calls
''')

# 用户原话落点：保存后按最终排期分区（排上的在已排期区）
sub('''    _save(agent, session)
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["source"]) for i in wish] == [("蜀风雅韵", "chat")]
''', '''    _save(agent, session)
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [(r["name"], r["source"]) for r in rows] == [("蜀风雅韵", "chat")]
''')

# 重说心愿只留一行（跨分区计一次）
sub('''    _save(agent, session)
    wish = svc.list_groups(iid)["wishlist"]
    assert [i["name"] for i in wish].count("灵隐寺") == 1
    assert [(i["name"], i["source"]) for i in wish] == [("灵隐寺", "manual")]

    row = svc.list_groups(iid)["wishlist"][0]
''', '''    _save(agent, session)
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [r["name"] for r in rows].count("灵隐寺") == 1
    assert [(r["name"], r["source"]) for r in rows] == [("灵隐寺", "manual")]

    row = next(r for r in rows if r["name"] == "灵隐寺")
''')
sub('''    run(agent.message(session, "还是想去灵隐寺"))
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["source"]) for i in wish] == [("灵隐寺", "manual")]
    assert svc.list_groups(iid)["unwanted"] == []
''', '''    run(agent.message(session, "还是想去灵隐寺"))
    _save(agent, session)
    rows = [r for zone in svc.list_groups(iid).values() for r in zone]
    assert [(r["name"], r["source"]) for r in rows] == [("灵隐寺", "manual")]
    assert svc.list_groups(iid)["unwanted"] == []
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
