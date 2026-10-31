"""API tests for §6.12 dual-lane routing: /plan/{id}/message lane dispatch,
slow-lane task endpoints, and the metrics endpoint.

Assembly mirrors tests/test_plan_api.py (stub adapters + dependency
overrides). TestClient without a context manager never starts the lifespan
worker — slow-lane tasks stay queued, which is exactly what we assert.
"""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.metrics import router as metrics_router
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
from app.services.gate import Lane, RequestGate
from app.services.itinerary import DayPlan, ItineraryPlan, VisitItem
from app.services.lane_metrics import get_lane_metrics
from app.services.llm.base import ChatResult
from app.services.task_queue import TaskStore

DEVICE = {"X-Device-ID": "device-1"}


class StubAdapter:
    name = "stub"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        assert self.replies, "scripted replies exhausted"
        self.calls += 1
        return ChatResult(content=self.replies.pop(0), model="stub")


class RuleOnlyGate(RequestGate):
    """真闸门 + 零脚本 Flash——快/慢用例只允许规则层命中（离线）；
    未命中文本走 escalate → main（闸门兜底路径）。"""

    def __init__(self) -> None:
        super().__init__(StubAdapter([]))


class AlwaysMainGate(RequestGate):
    """分类器替身：永远判 main——主车道用例证明完整 agent 管线。"""

    def __init__(self) -> None:
        super().__init__(StubAdapter([]))

    async def classify(self, text: str):
        from app.services.gate import LaneDecision

        return LaneDecision(
            lane=Lane.main, intent="chat", source="flash", latency_ms=0.0
        )


class StubPoiDetails:
    def get_by_name(self, city, name):
        return (
            {"opening_hours": "09:00-23:00", "hours_source": "amap"}
            if name == "洪崖洞"
            else None
        )

    def search_keyword(self, city, tokens, *, limit=5):
        return []


class StubTripItems:
    def list_groups(self, itinerary_id=None):
        return {"wishlist": [{"name": "洪崖洞"}]}


class StubTranslate:
    async def translate(self, text, *, source_lang, target_lang):
        raise AssertionError("translate not expected in these tests")


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


def make_app(agent, *, gate=None, fast_lane=None) -> tuple[FastAPI, PlanSessionStore]:
    app = FastAPI()
    sessions = PlanSessionStore()
    sessions.save(make_ready_session())
    store = TaskStore(":memory:")
    app.dependency_overrides[get_settings] = lambda: Settings(llm_backend="mock")
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: sessions
    app.dependency_overrides[get_task_store] = lambda: store
    app.dependency_overrides[get_request_gate] = (lambda g: lambda: g)(
        gate if gate is not None else RuleOnlyGate()
    )
    app.dependency_overrides[get_fast_lane] = lambda: (
        fast_lane
        if fast_lane is not None
        else FastLane(
            poi_details=StubPoiDetails(),
            trip_items=StubTripItems(),
            translate=StubTranslate(),
        )
    )
    app.include_router(plan_router)
    app.include_router(tasks_router)
    app.include_router(metrics_router)
    return app, sessions


def message(client, text):
    return client.post(
        "/api/v1/plan/sess-1/message", json={"text": text}, headers=DEVICE
    )


# --- fast lane ---


def test_fast_lane_answers_without_agent_llm():
    agent = PlanningAgentStubNever()
    client = TestClient(make_app(agent)[0])
    resp = message(client, "洪崖洞几点开门")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lane"]["lane"] == "fast"
    assert body["lane"]["intent"] == "poi_hours"
    assert "09:00-23:00" in body["reply"]


def PlanningAgentStubNever():
    from app.services.agent.plan import PlanningAgent

    class NeverAdapter(StubAdapter):
        name = "never"

        async def chat(self, messages, *, temperature=0.3, max_tokens=None):
            raise AssertionError("main model must not be called on the fast lane")

    return PlanningAgent(NeverAdapter([]))


def test_fast_lane_miss_falls_back_to_main_agent():
    # 「怎么去」命中 fast/navigation，但 FastLane v1 不支持 navigation →
    # 落主车道完整 agent 管线（宁缺毋错，不虚构答案）。
    agent = PlanningAgent(
        StubAdapter(['{"reply": "步行即可", "diffs": [], "need_clarification": []}'])
    )
    client = TestClient(make_app(agent)[0])
    resp = message(client, "长江索道怎么去")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lane"]["lane"] == "main"


# --- slow lane ---


def test_slow_lane_enqueue_returns_task_immediately():
    agent = PlanningAgentStubNever()  # 重排绝不在请求线程内跑
    client = TestClient(make_app(agent)[0])
    resp = message(client, "帮我重排一下行程")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lane"]["lane"] == "slow"
    task_id = body["lane"]["task_id"]
    assert task_id
    # 任务在队列里（TestClient 不启 lifespan worker）→ H5 轮询可见
    task = client.get(f"/api/v1/tasks/{task_id}", headers=DEVICE).json()
    assert task["status"] == "queued"
    assert task["kind"] == "replan"
    assert task["payload"]["session_id"] == "sess-1"


def test_task_endpoints_validation():
    app, _ = make_app(PlanningAgentStubNever())
    client = TestClient(app)
    assert (
        client.post("/api/v1/tasks", json={"kind": "mystery"}).status_code == 400
    )  # missing device id
    resp = client.post("/api/v1/tasks", json={"kind": "mystery"}, headers=DEVICE)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "unknown_task_kind"
    # bulk_extract 可入队
    resp = client.post(
        "/api/v1/tasks",
        json={"kind": "bulk_extract", "payload": {"texts": ["- 洪崖洞"]}},
        headers=DEVICE,
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]
    # 跨设备 404 防枚举
    other = {"X-Device-ID": "device-2"}
    assert client.get(f"/api/v1/tasks/{task_id}", headers=other).status_code == 404
    # 列表端点：只看本设备
    listing = client.get("/api/v1/tasks", headers=DEVICE).json()
    assert any(t["task_id"] == task_id for t in listing["tasks"])


# --- main lane unchanged ---


def test_main_lane_message_still_full_pipeline():
    agent = PlanningAgent(
        StubAdapter(['{"reply": "好的", "diffs": [], "need_clarification": []}'])
    )
    client = TestClient(make_app(agent, gate=AlwaysMainGate())[0])
    resp = message(client, "随便聊聊")
    assert resp.status_code == 200
    assert resp.json()["lane"]["lane"] == "main"


# --- metrics ---


def test_metrics_endpoint_reports_gate_and_lanes():
    get_lane_metrics().reset()
    agent = PlanningAgent(
        StubAdapter(['{"reply": "好的", "diffs": [], "need_clarification": []}'])
    )
    app, _ = make_app(agent)
    client = TestClient(app)
    message(client, "洪崖洞几点开门")  # fast
    message(client, "帮我重排一下行程")  # slow
    message(client, "随便聊聊")  # main（escalate → 完整 agent）
    resp = client.get("/api/v1/metrics/lanes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["gate"]["total"] == 3
    lanes = body["lanes"]
    assert lanes["total"] == 3
    assert lanes["lane_counts"] == {"fast": 1, "slow": 1, "main": 1}
    assert abs(lanes["off_main_share"] - 2 / 3) < 1e-9
    assert lanes["p95_ms"]["fast_ttft"] is not None
    assert lanes["p95_ms"]["fast_ttft"] < 1_000  # 快车道口径 <1s
    assert lanes["targets"]["off_main_share"] == 0.8
    assert set(lanes["met"]) == {
        "off_main_share",
        "fast_ttft_ms",
        "slow_accept_ms",
    }


def test_replan_worker_handler_roundtrip(monkeypatch):
    """慢车道 replan handler 后台跑完整管线：monkeypatch plan.py 的两个
    单例 getter（handler 函数体内直接调它们，dependency override 不生效）。"""
    from app.services.task_queue import TaskStore, TaskWorker, _replan_handler

    sessions = PlanSessionStore()
    sessions.save(make_ready_session())

    captured = {}

    class AgentStub:
        async def message(self, session, text):
            captured["text"] = text
            return session, "重排完成：第1天洪崖洞保留", None

        async def refresh_legs(self, session):
            captured["refresh_legs"] = True  # replan 新契约：变更后腿刷新

    import app.api.plan as plan_module

    monkeypatch.setattr(plan_module, "get_plan_sessions", lambda: sessions)
    monkeypatch.setattr(plan_module, "get_planning_agent", lambda: AgentStub())

    store = TaskStore(":memory:")
    task = store.enqueue(
        "replan",
        {"session_id": "sess-1", "device_id": "device-1", "text": "帮我重排一下行程"},
        device_id="device-1",
    )
    worker = TaskWorker(store)
    worker.register("replan", _replan_handler)
    assert asyncio.run(worker.tick()) is True
    done = store.get(task.task_id)
    assert done.status == "done"
    assert "重排完成" in done.result["reply"]
    assert captured["text"] == "帮我重排一下行程"
    assert captured.get("refresh_legs") is True  # 2026-10-30 重排后腿刷新


# --- missing session still 404s before any lane work ---


def test_message_unknown_session_404():
    agent = PlanningAgentStubNever()
    client = TestClient(make_app(agent)[0])
    resp = client.post(
        "/api/v1/plan/unknown/message", json={"text": "hi"}, headers=DEVICE
    )
    assert resp.status_code == 404
