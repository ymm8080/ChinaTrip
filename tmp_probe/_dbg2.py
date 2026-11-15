# -*- coding: utf-8 -*-
import asyncio, sys, json
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES\tests")
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

def _session(**kw):
    base = dict(session_id="sess-draft", device_id="device-1", cities=["上海"], days=1, plan=_plan(), state="ready")
    base.update(kw)
    return PlanSession(**base)

svc = TripItemService()
agent = PlanningAgent(StubAdapter(), trip_items=svc)
session = _session()
agent.sync_wishes_to_trip_items(session, ["豫园"])
print("after sync:", session.wish_sources)
agent._record_link_sites(session, ["城隍庙"], "")
print("after link:", session.wish_sources)
