# -*- coding: utf-8 -*-
import asyncio, json, logging, sqlite3, sys, time
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.stdout.reconfigure(encoding="utf-8")

from app.services.agent.plan import PlanSession, _mark_remote_visits
from app.services.itinerary.rules import validate_plan
from app.api.plan import get_planning_agent

DB = r"D:\CHINATRIP\CHINATRIP CODES\data\h5_state.db"

async def main():
    c = sqlite3.connect(DB)
    payload = c.execute("select payload from plan_sessions where rowid=2911").fetchone()[0]
    s = PlanSession.model_validate_json(payload)
    s.plan = None
    s.history = []
    s.assumptions = []
    s.session_id = "repro-1115-b"
    s.device_id = "repro-1115"
    s.state = "ready"
    agent = get_planning_agent()
    out = await agent._generate_v0(s)
    plan = out.plan
    _mark_remote_visits(plan)
    for d in plan.days:
        print("== Day", d.day)
        for it in d.items:
            print("   ", it.start_time, it.end_time, "|", it.name, "| remote", getattr(it,'remote',None), "| must", it.must, "| pinned", it.pinned, "| dur", it.duration_minutes)
    rep = validate_plan(plan, poi_hours=[])
    print("VIOLATIONS", len(rep.violations))
    for v in rep.violations:
        print("  !", v)

asyncio.run(main())

