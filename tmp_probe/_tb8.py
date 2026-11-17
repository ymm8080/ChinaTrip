# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''def run(coro):
    return asyncio.run(coro)
''', '''_LAST_SESSION: list = []


def run(coro):
    out = asyncio.run(coro)
    # message()/confirm_sites() 深拷贝会话：记住返回的活对象，供 _flush 做
    # 保存物化（2026-11-15：行只在保存时落库）。
    if isinstance(out, tuple) and out and hasattr(out[0], "wish_sources"):
        _LAST_SESSION[:] = [out[0]]
    return out
''')

sub('''    for agent, session in list(_SESSIONS):
        if agent._trip_items is not svc or session.plan is None:
            continue
        if session.plan.itinerary_id != iid:
            continue
        agent.commit_wish_drafts(session)
''', '''    candidates = list(_LAST_SESSION) + [s for _a, s in _SESSIONS]
    for session in candidates:
        if session.plan is None or session.plan.itinerary_id != iid:
            continue
        agent = next(
            (a for a, s in _SESSIONS if a._trip_items is svc),
            None,
        )
        if agent is None:
            continue
        agent.commit_wish_drafts(session)
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
