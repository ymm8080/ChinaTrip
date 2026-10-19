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
from app.services.agent.plan import (
    PlanningAgent,
    PlanSessionStore,
    _normalize_city,
    _parse_cities,
)
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import LLMError

DEVICE_HEADERS = {"X-Device-ID": "device-1"}

V0_JSON = json.dumps(
    {
        "items": [
            {
                "name": "西湖",
                "city": "杭州",
                "category": "sight",
                "day": 1,
                "duration_minutes": 120,
            },
            {
                "name": "雷峰塔",
                "city": "杭州",
                "category": "sight",
                "day": 2,
                "duration_minutes": 60,
            },
        ],
        "assumptions": [],
    },
    ensure_ascii=False,
)

EDIT_JSON = json.dumps(
    {
        "reply": "已把雷峰塔挪到第三天",
        "diffs": [{"op": "move", "item_id": "v2", "new_day": 3}],
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
        {"cities": ["上海", "杭州"], "days": 3, "preferences": "喜欢走路"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert body["session_id"]
    assert len(body["plan"]["days"]) == 3
    assert any("节奏" in a for a in body["assumptions"])
    assert isinstance(body["violations"], list)
    modes = [
        i.get("mode") for d in body["plan"]["days"] for i in d["items"] if "mode" in i
    ]
    # 出发段（第1天）+ 返程段（第3天）都经车次服务成行 = 目的地数+1 段
    assert modes == ["train", "train"]


def test_start_200_clarify_when_info_missing():
    agent = PlanningAgent(StubAdapter([]))  # no LLM call expected
    resp = start(client_for(agent), {})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "clarify"
    assert body["clarify"]
    assert "plan" not in body


def test_start_200_clarify_asks_preference_when_info_complete():
    agent = PlanningAgent(StubAdapter([]))  # no LLM call expected
    resp = start(client_for(agent), {"cities": ["上海"], "days": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "clarify"
    assert any(
        ("偏好" in q or "观光" in q) and "无特别要求" in q for q in body["clarify"]
    )
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
    session_id = start(
        client,
        {"cities": ["上海", "杭州"], "days": 3, "preferences": "博物馆"},
    ).json()["session_id"]
    resp = message(client, session_id, "把雷峰塔挪到第三天")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert "雷峰塔" in body["reply"]
    assert body["change"]["affected_items_count"] == 1
    # Day 3 is the 杭州→上海 return day, but the return leg departs in the
    # evening (no in-window train → 17:00 placeholder), so the moved POI
    # keeps the last-day morning slot: 末日 = 活动 + 返程.
    day2 = [i for i in body["plan"]["days"][1]["items"] if i["item_id"] == "v2"]
    day3 = [i for i in body["plan"]["days"][2]["items"] if i["item_id"] == "v2"]
    assert day3 and not day2
    assert any(i.get("mode") == "train" for i in body["plan"]["days"][2]["items"])


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


def test_message_llm_error_degrades_in_conversation():
    # Prod incident 1018: glm flash ReadTimeout on the edit turn -> 502
    # dead end. Contract now: retry once, then a friendly in-band reply;
    # the session and the plan survive.
    agent = PlanningAgent(ExplodingAdapter())
    client = client_for(agent)
    first = start(client, {"cities": ["北京"], "days": 1, "preferences": "博物馆"})
    assert first.status_code == 200  # v0 degrades to a placeholder, not 502
    assert any("LLM 不可用" in a for a in first.json()["assumptions"])
    resp = message(client, first.json()["session_id"], "改一下")
    assert resp.status_code == 200
    body = resp.json()
    assert "模型暂时无响应" in body["reply"]
    assert body["state"] == "ready"
    assert body["plan"]  # plan untouched, still delivered


# --- bilingual city input (H5 typed "Shanghai" used to fall back to Beijing) ---


def test_parse_cities_accepts_english_aliases_in_order():
    assert _parse_cities("Shanghai 5 days") == ["上海"]
    assert _parse_cities("Beijing to Chengdu via Xi'an") == ["北京", "成都", "西安"]
    assert _parse_cities("北京到shanghai，途经 suzhou") == ["北京", "上海", "苏州"]
    assert _parse_cities("no city here") == []


def test_normalize_city_maps_alias_and_keeps_chinese():
    assert _normalize_city("SHANGHAI") == "上海"
    assert _normalize_city("Xi'an") == "西安"
    assert _normalize_city("上海") == "上海"
    assert _normalize_city("  hangzhou ") == "杭州"


def test_start_parses_english_cities_from_preferences():
    # H5 no-session composer sends free text as preferences with no cities;
    # the English names must still start the plan instead of clarify→default.
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    resp = start(
        client_for(agent), {"days": 2, "preferences": "Shanghai then Hangzhou, museums"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert body["session_id"]


def test_message_clarify_answer_with_english_city_generates_plan():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    session_id = start(client, {}).json()["session_id"]  # clarify: info missing
    resp = message(client, session_id, "Shanghai and Hangzhou, 2 days, museums")
    assert resp.status_code == 200
    assert resp.json()["state"] == "ready"


# --- far link restaurant round: /message payload carries restos + plan -----


class _GeoAmap:
    def __init__(self, food_lat: float) -> None:
        self.food_lat = food_lat

    async def search_poi(self, keywords, *, city=None, page=1):
        if keywords == "景点":
            return [
                {
                    "name": "夫子庙",
                    "city": city or "南京",
                    "category": "风景名胜;古迹",
                    "source_poi_id": "B1",
                    "location": {"lon": 118.78, "lat": 32.00},
                }
            ]
        return [
            {
                "name": keywords,
                "city": city or "南京",
                "category": "餐饮服务;小吃店",
                "source_poi_id": "F1",
                "location": {"lon": 118.78, "lat": self.food_lat},
            }
        ]


class _Reader:
    def __init__(self, digest) -> None:
        self.digest = digest

    async def read(self, url: str):
        return self.digest


def test_message_food_link_far_returns_resto_confirm_payload():
    from app.services.trip_items import TripItemService
    from app.services.web_reader import LinkDigest

    v0 = json.dumps(
        {
            "items": [
                {"name": "夫子庙", "city": "南京", "category": "sight", "day": 1},
            ],
            "assumptions": [],
        },
        ensure_ascii=False,
    )
    sites = json.dumps(
        {"sites": [{"name": "李记锅贴", "kind": "food"}]}, ensure_ascii=False
    )
    agent = PlanningAgent(
        StubAdapter([sites, v0]),
        amap_client=_GeoAmap(food_lat=32.10),
        link_reader=_Reader(
            LinkDigest(
                url="https://xhslink.com/abc", title="南京必吃", text="李记锅贴绝了"
            )
        ),
        trip_items=TripItemService(),
    )
    client = client_for(agent)
    session_id = start(
        client, {"preferences": "按这个吃 https://xhslink.com/abc 规划"}
    ).json()["session_id"]

    resp = message(client, session_id, "南京 2 天")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "resto_confirm"
    assert [r["name"] for r in body["restos"]] == ["李记锅贴"]
    assert body["restos"][0]["nearest_km"] > 5
    assert "超过 5 公里" in body["reply"]
    assert any(d["items"] for d in body["plan"]["days"])  # v0 still delivered

    resp = message(client, session_id, "不安排")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    names = [i["name"] for d in body["plan"]["days"] for i in d["items"]]
    assert "李记锅贴" not in names
