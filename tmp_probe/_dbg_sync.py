# -*- coding: utf-8 -*-
import asyncio, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.trip_items import TripItemService
from app.services.itinerary import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from datetime import time
import json
from app.services.llm.base import ChatResult

class StubAdapter:
    name = "stub"
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        return ChatResult(content=json.dumps({"items": []}), model="stub")

plan = ItineraryPlan(itinerary_id="it-draft01", cities=["上海"], days=[DayPlan(day=1, base_city="上海", items=[VisitItem(item_id="v1", name="外滩", city="上海", day=1, start_time=time(9,0), end_time=time(10,30), duration_minutes=90, location=GeoPoint(lon=121.49, lat=31.24))])], start_date="2026-11-20")
s = PlanSession(session_id="s", device_id="d", cities=["上海"], days=1, plan=plan, state="ready")
svc = TripItemService()
agent = PlanningAgent(StubAdapter(), trip_items=svc)

notes, unresolved = asyncio.run(agent.sync_wishes_to_trip_items(s, ["豫园"]))
print("notes:", notes)
print("unresolved:", unresolved)
print("wish_sources:", s.wish_sources)
print("bindings:", s.wish_bindings)
