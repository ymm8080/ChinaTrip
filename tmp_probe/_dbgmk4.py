# -*- coding: utf-8 -*-
import io
body = '''# -*- coding: utf-8 -*-
from tests.test_plan_agent import (  # noqa: F401
    _ADD_FACE_SHOW,
    SH_HZ_ITEMS,
    ScriptedLLM,
    _ready_hz_session,
    edit_reply,
    run,
    v0_reply,
)
from app.services.agent.plan import PlanningAgent
from app.services.trip_items import TripItemService


def test_dbg2():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    print("IID_BEFORE", session.plan.itinerary_id)
    llm.replies.append(edit_reply("已加入", [_ADD_FACE_SHOW], wishes=["蜀风雅韵"]))
    run(agent.message(session, "我要去蜀风雅韵"))
    print("IID_AFTER", session.plan.itinerary_id)
    print("SOURCES", session.wish_sources)
    print("MUST", session.must_visits)
    print("BIND", list((session.wish_bindings or {}).keys()))
    agent.commit_wish_drafts(session)
    print("BOARD_ALL", {k: [i["name"] + "|" + str(i.get("itinerary_id")) for i in v] for k, v in svc.list_groups().items() if v})
    print("BOARD_IID", {k: [i["name"] for i in v] for k, v in svc.list_groups(session.plan.itinerary_id).items() if v})
'''
io.open(r"D:\CHINATRIP\CHINATRIP CODES\tests\test_dbg2.py", "w", encoding="utf-8", newline="\n").write(body)
print("ok")
