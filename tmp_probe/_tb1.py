# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''def _save(agent, session):
    """2026-11-15 用户拍板「心愿单只在保存新行程/保存修改/删除时进数据库」：
    规划回合只写会话态，行在保存时物化——断言行的用例先走一次保存。"""
    agent.commit_wish_drafts(session)
    return session
''', '''_PENDING_SAVE: dict = {}


def _save(agent, session):
    """2026-11-15 用户拍板「心愿单只在保存新行程/保存修改/删除时进数据库」：
    规划回合只写会话态，行在保存时物化——断言行的用例先走一次保存。"""
    iid = session.plan.itinerary_id if session.plan is not None else None
    _PENDING_SAVE[(id(agent._trip_items), iid)] = (agent, session)
    agent.commit_wish_drafts(session)
    return session


def _flush(svc, iid):
    """改走 _wish_row 的用例：这里补一次保存物化（同一会话只提交一次）。"""
    hit = _PENDING_SAVE.get((id(svc), iid))
    if hit is not None:
        hit[0].commit_wish_drafts(hit[1])
''')

sub('''def _wish_row(svc, iid, name):
    _save(agent, session)
    rows''', '''def _wish_row(svc, iid, name):
    _flush(svc, iid)
    rows''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
