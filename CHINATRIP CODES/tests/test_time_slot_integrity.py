# -*- coding: utf-8 -*-
"""Time-slot integrity: transfer-day untimed blind spot, deterministic
reconcile, degraded-solver fallback sequencing, and plan persistence.

Regression scope: user-reported "day 3 in Xiamen + 9am flight to
Chongqing" — an untimed departure-city visit on a transfer day used to
pass validation silently, and the plan never reached the itinerary
store (phantom itinerary_id, empty H5 行程 tab).
"""

import json
from datetime import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.itineraries import get_store
from app.api.itineraries import router as itineraries_router
from app.api.plan import get_plan_sessions, get_planning_agent
from app.api.plan import router as plan_router
from app.config import Settings, get_settings
from app.services.agent.plan import (
    PlanningAgent,
    PlanSessionStore,
    _fallback_sequence_times,
    _reconcile_transfer_days,
)
from app.services.itinerary import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
    validate_plan,
)
from app.services.itinerary_store import InMemoryItineraryStore
from app.services.llm.base import ChatResult

DEVICE_HEADERS = {"X-Device-ID": "device-tsi"}


def _visit(item_id, name, city, day, duration=90, start=None, pinned=False):
    end = None
    if start is not None:
        end = time(
            (start.hour * 60 + start.minute + duration) // 60 % 24,
            (start.hour * 60 + start.minute + duration) % 60,
        )
    return VisitItem(
        item_id=item_id,
        name=name,
        city=city,
        day=day,
        duration_minutes=duration,
        start_time=start,
        end_time=end,
        pinned=pinned,
    )


def _transfer(item_id, day, seq, frm, to, start, end):
    dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=seq,
        from_city=frm,
        to_city=to,
        mode="flight",
        start_time=start,
        end_time=end,
        duration_minutes=dur,
    )


def _xiamen_chongqing_plan():
    """Day 3: 9am XMN->CKG flight plus a stranded untimed Xiamen visit."""
    return ItineraryPlan(
        itinerary_id="it-tsi-1",
        cities=["厦门", "重庆"],
        days=[
            DayPlan(
                day=1,
                base_city="厦门",
                items=[
                    _visit("v1", "鼓浪屿", "厦门", 1, 120, time(9, 0)),
                ],
            ),
            DayPlan(
                day=2,
                base_city="厦门",
                items=[
                    _visit("v2", "南普陀寺", "厦门", 2, 90, time(9, 0)),
                ],
            ),
            DayPlan(
                day=3,
                base_city="厦门",
                items=[
                    _visit("v3", "曾厝垵", "厦门", 3, 90),  # untimed + wrong city
                    _transfer("t1", 3, 1, "厦门", "重庆", time(9, 0), time(12, 0)),
                    _visit("v4", "洪崖洞", "重庆", 3, 120),  # untimed arrival visit
                ],
            ),
            DayPlan(
                day=4,
                base_city="重庆",
                items=[
                    _visit("v5", "磁器口", "重庆", 4, 120, time(10, 0)),
                ],
            ),
        ],
    )


# --- rules: untimed visit on a transfer day is a hard error ---------------


def test_untimed_visit_on_transfer_day_is_error():
    plan = _xiamen_chongqing_plan()
    report = validate_plan(plan, poi_hours=[])
    untimed_errors = [
        v
        for v in report.violations
        if v.severity == "error" and "没有起止时间" in v.message
    ]
    assert untimed_errors, "untimed transfer-day visit must hard-fail"
    assert any("曾厝垵" in v.message for v in untimed_errors)


def test_timed_transfer_day_visits_pass_buffer_check():
    plan = _xiamen_chongqing_plan()
    for day in plan.days:
        for item in day.items:
            if isinstance(item, VisitItem) and item.start_time is None:
                day.items.remove(item)
    report = validate_plan(plan, poi_hours=[])
    assert not [v for v in report.violations if "没有起止时间" in v.message]


# --- reconcile: stranded departure-city visits move off the transfer day --


def test_reconcile_moves_stranded_visit_to_earlier_same_city_day():
    plan = _xiamen_chongqing_plan()
    notes = _reconcile_transfer_days(plan)
    day3 = plan.days[2]
    assert all(not (isinstance(i, VisitItem) and i.city == "厦门") for i in day3.items)
    moved = next(i for i in plan.days[1].items if i.item_id == "v3")
    assert moved.day == 2
    assert moved.start_time is not None
    assert any("曾厝垵" in n for n in notes)


def test_reconcile_drops_visit_when_no_earlier_same_city_day():
    plan = _xiamen_chongqing_plan()
    plan.days = plan.days[2:]  # no 厦门-base day before the flight day
    notes = _reconcile_transfer_days(plan)
    day3 = plan.days[0]
    assert all(not (isinstance(i, VisitItem) and i.city == "厦门") for i in day3.items)
    assert any("移除" in n for n in notes)


def test_reconcile_keeps_pinned_visits():
    plan = _xiamen_chongqing_plan()
    for day in plan.days:
        for item in day.items:
            if item.item_id == "v3":
                item.pinned = True
    notes = _reconcile_transfer_days(plan)
    day3 = plan.days[2]
    assert any(i.item_id == "v3" for i in day3.items)  # untouched
    assert notes == []


# --- fallback sequencing: solver degradation never ships 未排 -------------


def test_fallback_sequences_untimed_visits_around_transfer():
    plan = _xiamen_chongqing_plan()
    _reconcile_transfer_days(plan)
    _fallback_sequence_times(plan)
    for day in plan.days:
        for item in day.items:
            assert item.start_time is not None, f"{item.item_id} left untimed"
    # Arrival-city visit on the flight day must start after landing + buffer.
    hongyadong = next(i for d in plan.days for i in d.items if i.item_id == "v4")
    start_min = hongyadong.start_time.hour * 60 + hongyadong.start_time.minute
    assert start_min >= 12 * 60 + 90  # 12:00 landing + 90min iron-rule-4 buffer
    report = validate_plan(plan, poi_hours=[])
    assert report.ok, [v.message for v in report.violations]


# --- persistence: agent plans land in the itinerary store -----------------


V0_JSON = json.dumps(
    {
        "items": [
            {
                "name": "外滩",
                "city": "上海",
                "category": "sight",
                "day": 1,
                "duration_minutes": 90,
            },
            {
                "name": "西湖",
                "city": "杭州",
                "category": "sight",
                "day": 2,
                "duration_minutes": 120,
            },
        ],
        "assumptions": [],
    },
    ensure_ascii=False,
)


class StubAdapter:
    name = "stub"

    def __init__(self, replies):
        self.replies = list(replies)

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        assert self.replies, "scripted replies exhausted"
        return ChatResult(content=self.replies.pop(0), model="stub")


def make_app(agent):
    app = FastAPI()
    sessions = PlanSessionStore()
    itineraries = InMemoryItineraryStore()
    app.dependency_overrides[get_settings] = lambda: Settings(llm_backend="mock")
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: sessions
    app.dependency_overrides[get_store] = lambda: itineraries
    app.include_router(plan_router)
    app.include_router(itineraries_router)
    return app


def test_plan_start_persists_itinerary_for_h5_tab():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = TestClient(make_app(agent))
    resp = client.post(
        "/api/v1/plan/start",
        json={"cities": ["上海", "杭州"], "days": 2, "preferences": "地标美食"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    plan = resp.json()["plan"]
    iid = plan["itinerary_id"]

    got = client.get(f"/api/v1/itineraries/{iid}", headers=DEVICE_HEADERS)
    assert got.status_code == 200, "phantom itinerary_id must be retrievable"
    assert got.json()["itinerary_id"] == iid

    listed = client.get("/api/v1/itineraries", headers=DEVICE_HEADERS)
    assert iid in [r["itinerary_id"] for r in listed.json()]


def test_plan_message_updates_working_copy_version():
    edit_json = json.dumps(
        {
            "reply": "ok",
            "diffs": [{"op": "move", "item_id": "v1", "new_day": 2}],
            "need_clarification": [],
        },
        ensure_ascii=False,
    )
    agent = PlanningAgent(StubAdapter([V0_JSON, edit_json]))
    client = TestClient(make_app(agent))
    # Single-city session: under the 2026-10-19 origin rule the two-city
    # variant would drop 外滩 (origin) and strand 西湖 on the return-train
    # day, leaving no v1 to move. Here v1=外滩 exists and the move lands.
    start = client.post(
        "/api/v1/plan/start",
        json={"cities": ["上海"], "days": 2, "preferences": "地标美食"},
        headers=DEVICE_HEADERS,
    )
    sid = start.json()["session_id"]
    iid = start.json()["plan"]["itinerary_id"]

    msg = client.post(
        f"/api/v1/plan/{sid}/message",
        json={"text": "把外滩挪到第二天"},
        headers=DEVICE_HEADERS,
    )
    assert msg.status_code == 200
    got = client.get(f"/api/v1/itineraries/{iid}", headers=DEVICE_HEADERS)
    assert got.status_code == 200
    assert got.json()["working_sync_version"] >= 2
