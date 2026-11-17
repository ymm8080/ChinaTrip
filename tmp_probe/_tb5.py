# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''_PENDING_SAVE: dict = {}


def _save(agent, session):''', '''_PENDING_SAVE: dict = {}
# 会话登记：_wish_row 只拿到 (svc, iid)，靠它找到对应会话做保存物化
_SESSIONS: list = []


def _save(agent, session):''')

sub('''    iid = session.plan.itinerary_id if session.plan is not None else None
    _PENDING_SAVE[(id(agent._trip_items), iid)] = (agent, session)
    agent.commit_wish_drafts(session)
    return session


def _flush(svc, iid):
    """改走 _wish_row 的用例：这里补一次保存物化（同一会话只提交一次）。"""
    hit = _PENDING_SAVE.get((id(svc), iid))
    if hit is not None:
        hit[0].commit_wish_drafts(hit[1])
''', '''    _SESSIONS.append((agent, session))
    agent.commit_wish_drafts(session)
    return session


def _flush(svc, iid):
    """改走 _wish_row 的用例：这里补一次保存物化（规划期不写库，行在保存时
    才物化——2026-11-15 用户拍板）。"""
    for agent, session in list(_SESSIONS):
        if agent._trip_items is not svc or session.plan is None:
            continue
        if session.plan.itinerary_id != iid:
            continue
        agent.commit_wish_drafts(session)
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
