# -*- coding: utf-8 -*-
import asyncio, sqlite3, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.stdout.reconfigure(encoding="utf-8")
from app.services.agent.plan import PlanSession
from app.api.plan import get_planning_agent
from app.services import access_services as A
from app.services.itinerary import rules as R
from app.services.itinerary.legs import annotate_legs

DB = r"D:\CHINATRIP\CHINATRIP CODES\data\h5_state.db"
async def main():
    c = sqlite3.connect(DB)
    s = PlanSession.model_validate_json(c.execute("select payload from plan_sessions where rowid=2911").fetchone()[0])
    s.plan=None; s.history=[]; s.assumptions=[]; s.session_id="dbg"; s.device_id="dbg"; s.state="ready"
    agent = get_planning_agent()
    print("store injected:", A._STORE is not None)
    print("services_for:", [(x.service_name, x.departures()) for x in A.services_for("北京","慕田峪长城")])
    out = await agent._generate_v0(s)
    plan = out.plan
    d1 = plan.days[0]
    for i, it in enumerate(d1.items[:2]):
        print(i, it.item_id, it.name, it.start_time, it.end_time, "dep_times=", it.access_depart_times, "wait=", it.access_wait_minutes)
    a, b = d1.items[0], d1.items[1]
    print("manual breakdown:", R.access_breakdown(a, b))
asyncio.run(main())
