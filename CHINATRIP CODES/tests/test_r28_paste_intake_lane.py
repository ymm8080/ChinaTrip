# -*- coding: utf-8 -*-
"""R28 回归：无盘会话贴入完整行程文字，不得被慢车道吸成后台重排。

2026-11-24 用户实报「识别后之前是 HIGHLIGHT 让用户确认（可选中/取消），
现在变成纯 TEXT」：clarify 阶段（无盘）贴入整段 DayN 行程 → 线上 flash
分类器判 slow/replan → api/plan.py 慢车道分支直接入队重排任务并回纯文本
「收到，重排已在后台进行…」——读点确认轮（可选中/取消的高亮卡）从未开出。

类级修复：慢车道分支加 `session.plan is not None` 前置——慢车道的语义是
「重排已有行程」，无盘会话没有可重排的盘，贴文必须落主车道（7089d612 在
_answer_clarification 的开卡挂点 → site_confirm + sequence_ask）。

Assembly mirrors tests/test_lane_api.py（stub adapters + dependency overrides）。
"""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.plan import (
    get_fast_lane,
    get_plan_sessions,
    get_planning_agent,
    get_request_gate,
)
from app.api.plan import router as plan_router
from app.api.tasks import get_task_store
from app.api.tasks import router as tasks_router
from app.config import Settings, get_settings
from app.services.agent.plan import PlanningAgent, PlanSession, PlanSessionStore
from app.services.fast_lane import FastLane
from app.services.gate import Lane, LaneDecision, RequestGate
from app.services.itinerary import DayPlan, ItineraryPlan, VisitItem
from app.services.llm.base import ChatResult
from app.services.task_queue import TaskStore

DEVICE = {"X-Device-ID": "device-1"}


class StubAdapter:
    name = "stub"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        assert self.replies, "scripted replies exhausted"
        self.calls += 1
        return ChatResult(content=self.replies.pop(0), model="stub")


class AlwaysSlowGate(RequestGate):
    """复现线上劫持形态：分类器对贴文判 slow/replan（真闸门 flash 层行为）。"""

    def __init__(self) -> None:
        super().__init__(StubAdapter([]))

    async def classify(self, text: str):
        return LaneDecision(
            lane=Lane.slow, intent="replan", source="flash", latency_ms=0.0
        )


class StubPoiDetails:
    def get_by_name(self, city, name):
        return None

    def search_keyword(self, city, tokens, *, limit=5):
        return []


class StubTripItems:
    def list_groups(self, itinerary_id=None):
        return {"wishlist": []}


class StubTranslate:
    async def translate(self, text, *, source_lang, target_lang):
        raise AssertionError("translate not expected in these tests")


_KNOW_KEYS = ("天安门广场", "故宫博物院", "慕田峪长城")
_KNOWN = {
    ("北京", n): {"name": n, "city": "北京", "category": "风景名胜"}
    for n in _KNOW_KEYS
}


class Places:
    """底库桩：只认三座点名站（北京）。"""

    def candidate_by_name(self, city, name):
        return _KNOWN.get((city, (name or "").strip()))

    def match_text_names(self, city, text, *, limit=8):
        return [row for (c, n), row in _KNOWN.items() if c == city and n in text]


class NoPoiAmap:
    async def search_poi(self, keywords, *, city=None, page=1):
        return []


def make_clarify_session(session_id: str = "sess-1") -> PlanSession:
    """B2 实报形态：clarify 阶段（问城市/天数中）、plan=None、城市未定。"""
    return PlanSession(
        session_id=session_id,
        device_id="device-1",
        cities=[],
        state="clarify",
    )


def make_ready_session(session_id: str = "sess-1") -> PlanSession:
    plan = ItineraryPlan(
        itinerary_id="it-1",
        cities=["重庆"],
        days=[
            DayPlan(
                day=1,
                base_city="重庆",
                items=[VisitItem(item_id="v1", name="洪崖洞", city="重庆", day=1)],
            )
        ],
    )
    return PlanSession(
        session_id=session_id,
        device_id="device-1",
        cities=["重庆"],
        state="ready",
        plan=plan,
    )


def make_app(agent, *, gate, sessions):
    app = FastAPI()
    store = TaskStore(":memory:")
    app.dependency_overrides[get_settings] = lambda: Settings(llm_backend="mock")
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: sessions
    app.dependency_overrides[get_task_store] = lambda: store
    app.dependency_overrides[get_request_gate] = (lambda g: lambda: g)(gate)
    app.dependency_overrides[get_fast_lane] = lambda: FastLane(
        poi_details=StubPoiDetails(),
        trip_items=StubTripItems(),
        translate=StubTranslate(),
    )
    app.include_router(plan_router)
    app.include_router(tasks_router)
    return app, sessions


# 真实形状：英文贴文带城市词 + Day 标记（2026-11-24 用户实报原文形态）。
PASTE = (
    "Beijing 4 days. Day 1: Tiananmen Square in the morning, "
    "then the Forbidden City. Day 4: Mutianyu Great Wall hike."
)

_MINING_REPLY = json.dumps(
    {
        "sites": [
            {"name": "天安门广场", "kind": "sight", "city": "北京", "day": 1},
            {"name": "故宫博物院", "kind": "sight", "city": "北京", "day": 1},
            {"name": "慕田峪长城", "kind": "sight", "city": "北京", "day": 4},
        ]
    },
    ensure_ascii=False,
)


def test_planless_paste_falls_to_main_lane_and_opens_site_confirm():
    """无盘会话 + 分类器判 slow：贴文必须落主车道并开出读点确认轮
    (state=site_confirm、sites_source=brief、sequence_ask 在卡)，不得回
    「重排已在后台进行」纯文本。"""
    agent = PlanningAgent(
        StubAdapter([_MINING_REPLY]),
        amap_client=NoPoiAmap(),
        poi_details=Places(),
    )
    sessions = PlanSessionStore()
    sessions.save(make_clarify_session())
    client = TestClient(make_app(agent, gate=AlwaysSlowGate(), sessions=sessions)[0])
    resp = client.post(
        "/api/v1/plan/sess-1/message", json={"text": PASTE}, headers=DEVICE
    )
    assert resp.status_code == 200
    body = resp.json()
    # 修复点：不再是慢车道后台任务（纯文本 ack）
    assert body["lane"]["lane"] == "main"
    assert "task_id" not in (body.get("lane") or {})
    assert body.get("new_trip") is not True
    # 读点确认轮照常开出（高亮可选中/取消的卡）
    assert body["state"] == "site_confirm"
    assert body.get("sites_source") == "brief"
    assert "天安门广场" in (body.get("sites") or [])
    assert body["sequence_ask"]["days"]["慕田峪长城"] == 4


def test_ready_session_slow_lane_still_enqueues_replan():
    """有盘会话维持既有语义：slow 判定照常入队重排（守卫不越界）。"""
    agent = PlanningAgent(StubAdapter([]))
    sessions = PlanSessionStore()
    sessions.save(make_ready_session())
    client = TestClient(make_app(agent, gate=AlwaysSlowGate(), sessions=sessions)[0])
    resp = client.post(
        "/api/v1/plan/sess-1/message",
        json={"text": "帮我重排一下行程"},
        headers=DEVICE,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["lane"]["lane"] == "slow"
    assert body["lane"]["task_id"]
