# -*- coding: utf-8 -*-
import asyncio, json, logging, sqlite3, sys, time
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from app.services.agent.plan import PlanSession
from app.api.plan import get_planning_agent

DB = r"D:\CHINATRIP\CHINATRIP CODES\data\h5_state.db"

async def main():
    c = sqlite3.connect(DB)
    payload = c.execute("select payload from plan_sessions where rowid=2911").fetchone()[0]
    s = PlanSession.model_validate_json(payload)
    s.plan = None
    s.history = []
    s.assumptions = []
    s.session_id = "repro-1115-a"
    s.device_id = "repro-1115"
    s.state = "ready"
    print("INPUT days", s.days, "cities", s.cities, "must", s.must_visits, "start", s.start_date)
    agent = get_planning_agent()
    t0 = time.time()
    out = await agent._generate_v0(s)
    print("elapsed", round(time.time()-t0, 1))
    plan = out.plan
    print("assumptions:")
    for a in plan.assumptions:
        print("  -", a)
    for d in plan.days:
        print("== Day", d.day)
        for it in d.items:
            print("   ", it.start_time, it.end_time, "|", it.name, "|", it.category, "| must", it.must, "| pinned", it.pinned, "| dur", it.duration_minutes, "| walk", it.next_walk_minutes, "| km", it.distance_to_next_km)

asyncio.run(main())
