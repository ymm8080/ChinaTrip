# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_wish_draft_lifecycle.py"
src = '''"""心愿单随行程走（2026-11-14 用户拍板）回归。

ISSUE1：删行程 = 名下心愿单一并删除（见 test_trip_items.py）。
ISSUE2：没点「💾 保存行程」→ 规划会话建的心愿行是草稿，看板/心愿单视图
不返回；保存行程时转正。本文件覆盖草稿标记的生命周期。
"""

import json
from datetime import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.itineraries import get_entitlement_service, get_store
from app.api.itineraries import router as itineraries_router
from app.api.plan import get_plan_sessions, get_planning_agent
from app.api.plan import router as plan_router
from app.services.agent.plan import PlanningAgent, PlanSession, PlanSessionStore
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.itinerary import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.itinerary_store import InMemoryItineraryStore
from app.services.llm.base import ChatResult
from app.services.trip_items import TripItemService

DEVICE_HEADERS = {"X-Device-ID": "device-1"}


class StubAdapter:
    name = "stub"

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        return ChatResult(content=json.dumps({"items": []}), model="stub")


def _plan(itinerary_id: str = "it-draft01") -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id=itinerary_id,
        cities=["上海"],
        days=[
            DayPlan(
                day=1,
                base_city="上海",
                items=[
                    VisitItem(
                        item_id="v1",
                        name="外滩",
                        city="上海",
                        day=1,
                        start_time=time(9, 0),
                        end_time=time(10, 30),
                        duration_minutes=90,
                        location=GeoPoint(lon=121.49, lat=31.24),
                    )
                ],
            )
        ],
        start_date="2026-11-20",
    )


def _session(session_id: str = "sess-draft", **kwargs) -> PlanSession:
    base = dict(
        session_id=session_id,
        device_id="device-1",
        cities=["上海"],
        days=1,
        plan=_plan(),
        state="ready",
    )
    base.update(kwargs)
    return PlanSession(**base)


def test_wish_rows_from_unsaved_session_are_drafts():
    svc = TripItemService()
    agent = PlanningAgent(StubAdapter(), trip_items=svc)
    session = _session()

    agent._record_link_sites(session, ["豫园"], "")

    rows = svc.list_groups()["wishlist"]
    assert [r["name"] for r in rows] == ["豫园"]
    assert rows[0]["draft_session_id"] == session.session_id
    assert svc.list_groups(include_drafts=False)["wishlist"] == []


def test_wish_rows_from_saved_trip_are_immediate():
    svc = TripItemService()
    agent = PlanningAgent(StubAdapter(), trip_items=svc)
    # ✏️ 修改已存行程：行程本身已在库，心愿行即时生效
    session = _session(source_itinerary_id="it-draft01")

    agent._record_link_sites(session, ["豫园"], "")

    rows = svc.list_groups(include_drafts=False)["wishlist"]
    assert [r["name"] for r in rows] == ["豫园"]
    assert rows[0]["draft_session_id"] is None


def test_wish_draft_session_flag_rules():
    agent = PlanningAgent(StubAdapter(), trip_items=TripItemService())
    assert agent._wish_draft_session(_session()) == "sess-draft"
    assert agent._wish_draft_session(_session(wish_committed=True)) is None
    assert agent._wish_draft_session(_session(source_itinerary_id="it-x")) is None


def test_save_endpoint_commits_session_drafts():
    """点「💾 保存行程」→ 本会话草稿转正：看板可见、draft 标记清空。"""
    svc = TripItemService()
    agent = PlanningAgent(StubAdapter(), trip_items=svc)
    store = PlanSessionStore()
    itineraries = InMemoryItineraryStore()
    session = _session()
    store.save(session)
    draft = svc.create(
        "豫园",
        source="chat",
        itinerary_id=session.plan.itinerary_id,
        owner_device_id="device-1",
        city="上海",
        draft_session_id=session.session_id,
    )
    assert svc.list_groups(include_drafts=False)["wishlist"] == []

    app = FastAPI()
    app.dependency_overrides[get_plan_sessions] = lambda: store
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_store] = lambda: itineraries
    app.dependency_overrides[get_entitlement_service] = lambda: EntitlementService(
        InMemoryQuotaStore(), rules=[]
    )
    app.include_router(plan_router)
    app.include_router(itineraries_router)

    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/plan/{session.session_id}/save", json={}, headers=DEVICE_HEADERS
        )
    assert resp.status_code == 201
    committed = svc.get(draft["id"])
    assert committed["draft_session_id"] is None
    assert committed["itinerary_id"] == session.plan.itinerary_id
    assert [r["name"] for r in svc.list_groups(include_drafts=False)["wishlist"]] == [
        "豫园"
    ]
    assert store.get(session.session_id, device_id="device-1").wish_committed is True
'''
io.open(p, "w", encoding="utf-8", newline="\r\n").write(src)
print("wrote", p)
