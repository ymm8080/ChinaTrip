"""Plan API tests: /api/v1/plan/start + /plan/{id}/message.

App assembly mirrors tests/test_translate_api.py: stub adapters, fresh
PlanSessionStore per app, dependency overrides only.
"""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.plan import get_plan_sessions, get_planning_agent
from app.api.plan import router as plan_router
from app.config import Settings, get_settings
from app.services.agent.plan import PlanningAgent, PlanSessionStore
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import LLMError

DEVICE_HEADERS = {"X-Device-ID": "device-1"}

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
                "name": "豫园",
                "city": "上海",
                "category": "sight",
                "day": 1,
                "duration_minutes": 60,
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

EDIT_JSON = json.dumps(
    {
        "reply": "已把豫园挪到第二天",
        "diffs": [{"op": "move", "item_id": "v2", "new_day": 2}],
        "need_clarification": [],
    },
    ensure_ascii=False,
)


class StubAdapter:
    name = "stub"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        assert self.replies, "scripted replies exhausted"
        return ChatResult(content=self.replies.pop(0), model="stub")


class ExplodingAdapter:
    name = "explode"

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise LLMError("backend down")


def make_app(agent: PlanningAgent) -> FastAPI:
    app = FastAPI()
    store = PlanSessionStore()  # one store per app, like the prod singleton
    app.dependency_overrides[get_settings] = lambda: Settings(llm_backend="mock")
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: store
    app.include_router(plan_router)
    return app


def client_for(agent: PlanningAgent) -> TestClient:
    return TestClient(make_app(agent))


def start(client: TestClient, body: dict, headers=None):
    return client.post(
        "/api/v1/plan/start", json=body, headers=headers or DEVICE_HEADERS
    )


def message(client: TestClient, session_id: str, text: str, headers=None):
    return client.post(
        f"/api/v1/plan/{session_id}/message",
        json={"text": text},
        headers=headers or DEVICE_HEADERS,
    )


# --- POST /plan/start ------------------------------------------------------


def test_start_200_ready_with_plan_assumptions_and_violations():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    resp = start(
        client_for(agent),
        {"cities": ["上海", "杭州"], "days": 2, "preferences": "喜欢走路"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert body["session_id"]
    assert len(body["plan"]["days"]) == 2
    assert any("节奏" in a for a in body["assumptions"])
    assert isinstance(body["violations"], list)
    modes = [
        i.get("mode") for d in body["plan"]["days"] for i in d["items"] if "mode" in i
    ]
    assert modes == ["train"]  # cross-city TransferItem via the train service


def test_start_200_clarify_when_info_missing():
    agent = PlanningAgent(StubAdapter([]))  # no LLM call expected
    resp = start(client_for(agent), {})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "clarify"
    assert body["clarify"]
    assert "plan" not in body


def test_start_missing_device_id_returns_400():
    agent = PlanningAgent(StubAdapter([]))
    resp = client_for(agent).post(
        "/api/v1/plan/start", json={"cities": ["北京"], "days": 1}
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "missing_device_id"}


# --- POST /plan/{session_id}/message ---------------------------------------


def test_message_200_applies_diff_and_returns_change():
    agent = PlanningAgent(StubAdapter([V0_JSON, EDIT_JSON]))
    client = client_for(agent)
    session_id = start(client, {"cities": ["上海", "杭州"], "days": 2}).json()[
        "session_id"
    ]
    resp = message(client, session_id, "把豫园挪到第二天")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert "豫园" in body["reply"]
    assert body["change"]["affected_items_count"] == 1
    moved = [i for i in body["plan"]["days"][1]["items"] if i["item_id"] == "v2"]
    assert moved


def test_message_unknown_session_returns_404():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    resp = message(client_for(agent), "no-such-session", "改一下")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session_not_found"}


def test_message_other_device_returns_404():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    session_id = start(client, {"cities": ["北京"], "days": 1}).json()["session_id"]
    resp = message(client, session_id, "改一下", headers={"X-Device-ID": "device-2"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session_not_found"}


def test_message_llm_error_maps_to_502():
    agent = PlanningAgent(ExplodingAdapter())
    client = client_for(agent)
    first = start(client, {"cities": ["北京"], "days": 1})
    assert first.status_code == 200  # v0 degrades to a placeholder, not 502
    assert any("LLM 不可用" in a for a in first.json()["assumptions"])
    resp = message(client, first.json()["session_id"], "改一下")
    assert resp.status_code == 502
    assert resp.json() == {"detail": "llm_error"}
