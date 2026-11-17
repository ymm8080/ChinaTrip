# -*- coding: utf-8 -*-
import asyncio, sys, json
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from datetime import time
from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.trip_items import TripItemService
from app.services.itinerary import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.llm.base import ChatResult

class StubAdapter:
    name = "stub"
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        return ChatResult(content=json.dumps({"items": []}), model="stub")

def _plan():
    return ItineraryPlan(itinerary_id="it-draft01", cities=["上海"], days=[DayPlan(day=1, base_city="上海", items=[VisitItem(item_id="v1", name="外滩", city="上海", day=1, start_time=time(9,0), end_time=time(10,30), duration_minutes=90, location=GeoPoint(lon=121.49, lat=31.24))])], start_date="2026-11-20")

s = PlanSession(session_id="s", device_id="device-1", cities=["上海"], days=1, plan=_plan(), state="ready")
s.must_visits = ["豫园"]
s.wish_sources = {"豫园": {"source": "chat", "note": "来自聊天", "city": "上海"}}
s.avoid_sites = ["迪士尼"]
s.plan.days[0].items.append(VisitItem(item_id="v2", name="豫园", poi_id="B-YUYUAN", city="上海", day=1, start_time=time(11,0), end_time=time(12,30), duration_minutes=90, location=GeoPoint(lon=121.49, lat=31.23)))
svc = TripItemService()
agent = PlanningAgent(StubAdapter(), trip_items=svc)
n = agent.commit_wish_drafts(s, account="acc-1")
print("committed:", n)
for g, rows in svc.list_groups().items():
    print(g, [(r["name"], r.get("day"), r.get("status"), (r.get("note") or "")[:30]) for r in rows])
