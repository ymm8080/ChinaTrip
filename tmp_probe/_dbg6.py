# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES\tests")
from datetime import time as clock_time
from app.services.agent.plan import PlanningAgent
from app.services.itinerary import VisitItem
from app.services.itinerary.models import DayPlan, ItineraryPlan
from app.services.trip_items import TripItemService
from tests.test_wish_bind import CountingLLM, PandaStore

def _agent(svc):
    return PlanningAgent(CountingLLM(), trip_items=svc, poi_details=PandaStore(), auto_restaurants=False)

def _plan_with(items):
    return ItineraryPlan(itinerary_id="it-test", cities=["成都"], days=[DayPlan(day=1, base_city="成都", items=items)])

def _item(name, *, poi_id="POI1", cat="attraction", day=1, start="09:00"):
    return VisitItem(item_id=f"v-{name}", name=name, city="成都", day=day, duration_minutes=120, category=cat, poi_id=poi_id, start_time=clock_time.fromisoformat(start))

svc = TripItemService()
svc.create("看熊猫", source="chat", city="成都")
agent = _agent(svc)
agent._wish_bindings["看熊猫"] = {"name": "成都大熊猫繁育研究基地", "city": "成都", "source_poi_id": "PANDA01", "location": {"lon": 104.1, "lat": 30.7}}
from app.services.agent.plan import PlanSession
session = PlanSession(session_id="s1", device_id="d1", cities=["成都"])
session.plan = _plan_with([_item("成都大熊猫繁育研究基地", poi_id="PANDA01")])
agent._sync_wish_rows(session, at_save=True)
groups = svc.list_groups("it-test")
print({g: [(r["name"], r.get("status"), r.get("itinerary_id")) for r in rows] for g, rows in groups.items() if rows})
