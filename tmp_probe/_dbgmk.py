# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_dbg_wish.py"
body = '''# -*- coding: utf-8 -*-
import json

from tests.test_plan_agent import (  # noqa: F401
    _ADD_FACE_SHOW,
    SH_HZ_ITEMS,
    ScriptedLLM,
    _ready_hz_session,
    all_visits,
    edit_reply,
    run,
    v0_reply,
)
from app.services.agent.plan import PlanningAgent
from app.services.trip_items import TripItemService


def test_dbg():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    iid = session.plan.itinerary_id
    llm.replies.append(edit_reply("已加入", [_ADD_FACE_SHOW], wishes=["看变脸表演"]))
    session, reply, _ = run(agent.message(session, "我想看变脸表演"))
    print("WISH_SOURCES", session.wish_sources)
    print("MUST", session.must_visits)
    print("CREATED", getattr(session, "created_sites", None))
    print("BINDINGS", list((session.wish_bindings or {}).keys()))
    print("REPLY", reply[:80])
    n = agent.commit_wish_drafts(session)
    print("COMMITTED", n)
    print("BOARD", {k: [i["name"] for i in v] for k, v in svc.list_groups(iid).items() if v})
'''
io.open(p, "w", encoding="utf-8", newline="\n").write(body)
print("dbg test written")
