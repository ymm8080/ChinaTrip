"""Plan API tests: /api/v1/plan/start + /plan/{id}/message.

App assembly mirrors tests/test_translate_api.py: stub adapters, fresh
PlanSessionStore per app, dependency overrides only.
"""

import json
import os
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.itineraries import (
    _account_from_auth,
    get_entitlement_service,
    get_store,
)
from app.api.itineraries import router as itineraries_router
from app.api.plan import (
    get_fast_lane,
    get_plan_sessions,
    get_planning_agent,
    get_request_gate,
    get_task_store,
)
from app.api.plan import router as plan_router
from app.config import Settings, get_settings
from app.middleware.lang import LangMiddleware
from app.services.agent.plan import (
    PlanningAgent,
    PlanSessionStore,
    _normalize_city,
    _parse_cities,
)
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.gate import RequestGate
from app.services.itinerary import VisitItem
from app.services.itinerary_store import InMemoryItineraryStore
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
    itineraries = InMemoryItineraryStore()
    entitlement = EntitlementService(InMemoryQuotaStore(), rules=[])
    app.dependency_overrides[get_settings] = lambda: Settings(llm_backend="mock")
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: store
    app.dependency_overrides[get_store] = lambda: itineraries
    app.dependency_overrides[get_entitlement_service] = lambda: entitlement
    # §6.12 双车道依赖（2026-10-27）：不 override 会在全套联跑时命中
    # 进程级单例（真实 zhipu 适配器/真任务库）——消息用例必须确定性离线。
    app.dependency_overrides[get_request_gate] = lambda: RequestGate(
        ExplodingAdapter()
    )  # Flash 不可用 → escalate → main，与旧行为一致
    from app.services.fast_lane import FastLane

    app.dependency_overrides[get_fast_lane] = lambda: FastLane(
        poi_details=_NoopPoi(),
        trip_items=_NoopTrip(),
        translate=_NoopTranslate(),
    )
    from app.services.task_queue import TaskStore

    _task_store = TaskStore(":memory:")
    app.dependency_overrides[get_task_store] = lambda: _task_store
    app.include_router(plan_router)
    app.include_router(itineraries_router)
    return app


class _NoopPoi:
    def get_by_name(self, city, name):
        return None

    def search_keyword(self, city, tokens, *, limit=5):
        return []


class _NoopTrip:
    def list_groups(self, itinerary_id=None):
        return {"wishlist": []}


class _NoopTranslate:
    async def translate(self, text, *, source_lang, target_lang):
        raise AssertionError("translate fast lane not expected in plan_api tests")


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


# --- product rule 2026-10-20: sites/confirm endpoint --------------------


class NoPoiAmap:
    async def search_poi(self, keywords, *, city=None, page=1):
        return []


class LinkReaderStub:
    def __init__(self, digest):
        self.digest = digest

    async def read(self, url):
        return self.digest


def test_sites_confirm_endpoint_writes_only_picked():
    from app.services.trip_items import TripItemService
    from app.services.web_reader import LinkDigest

    svc = TripItemService()
    digest = LinkDigest(url="https://x/1", title="杭州两日", text="西湖灵隐寺西溪")
    agent = PlanningAgent(
        StubAdapter(
            [
                V0_JSON,
                json.dumps(
                    {"sites": ["西湖", "灵隐寺", "西溪湿地"]}, ensure_ascii=False
                ),
            ]
        ),
        amap_client=NoPoiAmap(),
        link_reader=LinkReaderStub(digest),
        trip_items=svc,
    )
    client = client_for(agent)
    started = start(
        client, {"cities": ["杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    assert started["state"] == "ready"
    sid = started["session_id"]
    body = message(client, sid, "https://x/1 参考").json()
    assert body["state"] == "site_confirm"
    assert body["sites"] == ["西湖", "灵隐寺", "西溪湿地"]

    # another device cannot confirm someone else's session
    r = client.post(
        f"/api/v1/plan/{sid}/sites/confirm",
        json={"mandatory": ["西湖"]},
        headers={"X-Device-ID": "device-2"},
    )
    assert r.status_code == 404

    r = client.post(
        f"/api/v1/plan/{sid}/sites/confirm",
        json={"mandatory": ["西湖"]},
        headers=DEVICE_HEADERS,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "ready"
    assert data["plan"] is not None
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["西湖"]
    assert "未点选的 2 个地点没有写入心愿单" in data["reply"]

    # the round is closed: a second confirm is a 409
    r = client.post(
        f"/api/v1/plan/{sid}/sites/confirm",
        json={"mandatory": ["灵隐寺"]},
        headers=DEVICE_HEADERS,
    )
    assert r.status_code == 409


# --- POST /plan/{id}/save：显式落库（2026-10-20 产品规则） -------------------


def test_save_upserts_record_and_freezes_snapshot():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "地标美食"}
    ).json()
    sid = body["session_id"]
    iid = body["plan"]["itinerary_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/save", json={"name": "江浙两日"}, headers=DEVICE_HEADERS
    )
    assert resp.status_code == 201
    meta = resp.json()
    assert meta["name"] == "江浙两日"
    assert meta["sync_version"] == 1
    assert "plan" not in meta
    got = client.get(f"/api/v1/itineraries/{iid}", headers=DEVICE_HEADERS)
    assert got.status_code == 200
    assert got.json()["snapshots"][0]["name"] == "江浙两日"


def test_save_persists_start_date_for_old_itineraries():
    # 旧行程自愈（2026-10-25）：itinEdit 对没存过出发日期的行程缺省今天，
    # 保存时随请求落库——下次打开不再日期/天气双盲
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "地标美食"}
    ).json()
    sid, iid = body["session_id"], body["plan"]["itinerary_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/save",
        json={"name": "自愈", "start_date": "2026-11-01"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 201
    reopened = client.post(
        f"/api/v1/plan/from-itinerary/{iid}", json={}, headers=DEVICE_HEADERS
    )
    assert reopened.status_code == 201
    assert reopened.json()["plan"]["start_date"] == "2026-11-01"


def test_save_before_any_plan_returns_400():
    agent = PlanningAgent(StubAdapter([]))
    client = client_for(agent)
    resp = start(client, {})  # no cities -> clarify, plan stays None
    assert resp.status_code == 200
    assert resp.json()["state"] == "clarify"
    sid = resp.json()["session_id"]
    resp = client.post(f"/api/v1/plan/{sid}/save", json={}, headers=DEVICE_HEADERS)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "nothing_to_save"


def test_save_unknown_or_foreign_session_404():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    sid = start(client, {"cities": ["上海"], "days": 1}).json()["session_id"]
    assert (
        client.post(
            f"/api/v1/plan/{sid}/save", json={}, headers={"X-Device-ID": "device-2"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/plan/snap_unknown/save", json={}, headers=DEVICE_HEADERS
        ).status_code
        == 404
    )


def test_save_quota_denied_returns_402_with_trigger():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    app = make_app(agent)
    app.dependency_overrides[get_entitlement_service] = lambda: EntitlementService(
        InMemoryQuotaStore(), rules=[], quotas={"snapshot_limit": 0}
    )
    client = TestClient(app)
    sid = start(
        client, {"cities": ["上海"], "days": 1, "preferences": "地标美食"}
    ).json()["session_id"]
    resp = client.post(f"/api/v1/plan/{sid}/save", json={}, headers=DEVICE_HEADERS)
    assert resp.status_code == 402
    assert resp.json()["detail"]["paywall_trigger"] == "snapshot_limit_hit"


def test_save_claims_to_account_via_auth_dependency():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    app = make_app(agent)
    app.dependency_overrides[_account_from_auth] = lambda: "acc-1"
    client = TestClient(app)
    body = start(
        client, {"cities": ["上海"], "days": 1, "preferences": "地标美食"}
    ).json()
    sid, iid = body["session_id"], body["plan"]["itinerary_id"]
    # 认证依赖已被 override：设备头即可触发账号认领断言
    assert (
        client.post(
            f"/api/v1/plan/{sid}/save", json={}, headers=DEVICE_HEADERS
        ).status_code
        == 201
    )
    got = client.get(f"/api/v1/itineraries/{iid}", headers=DEVICE_HEADERS)
    assert got.status_code == 200
    assert got.json()["owner_account_id"] == "acc-1"


# --- POST /plan/from-itinerary/{id}：「行程」页 ✏️ 修改（2026-10-20）------


def test_from_itinerary_opens_ready_session_and_round_trips_save():
    agent = PlanningAgent(StubAdapter([V0_JSON, EDIT_JSON]))
    app = make_app(agent)
    app.dependency_overrides[get_entitlement_service] = lambda: EntitlementService(
        InMemoryQuotaStore(), rules=[], quotas={"snapshot_limit": 3}
    )
    client = TestClient(app)
    saved = start(
        client,
        {
            "cities": ["上海", "杭州"],
            "days": 3,
            "preferences": "博物馆",
            "start_date": "2026-10-25",
        },
    ).json()
    iid = saved["plan"]["itinerary_id"]
    assert saved["plan"]["start_date"] == "2026-10-25"
    assert (
        client.post(
            f"/api/v1/plan/{saved['session_id']}/save",
            json={},
            headers=DEVICE_HEADERS,
        ).status_code
        == 201
    )
    resp = client.post(
        f"/api/v1/plan/from-itinerary/{iid}", json={}, headers=DEVICE_HEADERS
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["state"] == "ready"
    assert body["session_id"]
    assert body["plan"]["itinerary_id"] == iid  # 同一行程：保存覆盖原记录
    assert body["plan"]["cities"] == ["上海", "杭州"]
    # 出发日期随快照持久化：保存→重开一路带回（行程卡日期/天气基准）
    assert body["plan"]["start_date"] == "2026-10-25"
    # 载入后可继续对话修改，再保存 = 同一条行程的新版本 + 新快照。
    edited = message(client, body["session_id"], "把雷峰塔挪到第三天")
    assert edited.status_code == 200
    assert edited.json()["plan"]["itinerary_id"] == iid
    assert (
        client.post(
            f"/api/v1/plan/{body['session_id']}/save",
            json={},
            headers=DEVICE_HEADERS,
        ).status_code
        == 201
    )
    rec = client.get(f"/api/v1/itineraries/{iid}", headers=DEVICE_HEADERS).json()
    assert rec["working_sync_version"] == 2
    assert len(rec["snapshots"]) == 2
    # 时间戳语义（2026-10-20）：created_at 是首存时间，updated_at 随再保存刷新。
    created = datetime.fromisoformat(rec["created_at"])
    updated = datetime.fromisoformat(rec["updated_at"])
    assert updated >= created


def test_from_itinerary_session_lang_follows_x_lang_header():
    """✏️ 修改会话语言随 X-Lang 头（2026-10-30 修复）：建档漏 lang 时
    编辑回合系统提示词不挂英文输出指令，英文界面下 LLM 回复恒中文。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    app = make_app(agent)
    app.add_middleware(LangMiddleware)  # 生产在 app/main.py 挂载，同链路
    client = TestClient(app)
    saved = start(
        client, {"cities": ["上海", "杭州"], "days": 3, "preferences": "博物馆"}
    ).json()
    iid = saved["plan"]["itinerary_id"]
    assert (
        client.post(
            f"/api/v1/plan/{saved['session_id']}/save",
            json={},
            headers=DEVICE_HEADERS,
        ).status_code
        == 201
    )
    en = client.post(
        f"/api/v1/plan/from-itinerary/{iid}",
        json={},
        headers={**DEVICE_HEADERS, "X-Lang": "en"},
    )
    assert en.status_code == 201
    store = app.dependency_overrides[get_plan_sessions]()
    session_en = store.get(en.json()["session_id"], device_id="device-1")
    assert session_en.lang == "en"
    assert "MUST be natural English" in PlanningAgent._edit_system_prompt(session_en)
    # 不带头的默认（中文站）行为不变：无英文输出指令
    zh = client.post(
        f"/api/v1/plan/from-itinerary/{iid}", json={}, headers=DEVICE_HEADERS
    )
    assert zh.status_code == 201
    session_zh = store.get(zh.json()["session_id"], device_id="device-1")
    assert session_zh.lang != "en"
    assert "MUST be natural English" not in PlanningAgent._edit_system_prompt(
        session_zh
    )


def test_from_itinerary_unknown_or_foreign_id_404():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    saved = start(
        client, {"cities": ["上海"], "days": 2, "preferences": "博物馆"}
    ).json()
    iid = saved["plan"]["itinerary_id"]
    client.post(
        f"/api/v1/plan/{saved['session_id']}/save",
        json={},
        headers=DEVICE_HEADERS,
    )
    foreign = {"X-Device-ID": "device-2"}
    assert (
        client.post(
            f"/api/v1/plan/from-itinerary/{iid}", json={}, headers=foreign
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/plan/from-itinerary/it_none",
            json={},
            headers=DEVICE_HEADERS,
        ).status_code
        == 404
    )
    # 原行程不受伤：物主仍可打开。
    assert (
        client.post(
            f"/api/v1/plan/from-itinerary/{iid}",
            json={},
            headers=DEVICE_HEADERS,
        ).status_code
        == 201
    )


def test_from_itinerary_missing_device_id_returns_400():
    agent = PlanningAgent(StubAdapter([]))
    client = client_for(agent)
    resp = client.post("/api/v1/plan/from-itinerary/it_none", json={})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "missing_device_id"


# --- POST /plan/{id}/items/{item_id}/pin + /delete（2026-10-20）-------------


class UnwantRecorder:
    """trip-item service stub: mark_unwanted + an empty wishlist."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str | None]] = []

    def list_groups(self, itinerary_id: str | None = None) -> dict:
        return {"wishlist": [], "scheduled": [], "booked": [], "unwanted": []}

    def mark_unwanted(self, name, *, itinerary_id=None, city=None):
        self.calls.append((name, itinerary_id, city))
        return {"name": name, "status": "unwanted"}


def _visit(body: dict, name: str) -> dict:
    return next(
        i
        for d in body["plan"]["days"]
        for i in d["items"]
        if i.get("name") == name and "mode" not in i
    )


def test_pin_and_unpin_flip_pinned_in_plan():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    vid = _visit(body, "西湖")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{body['session_id']}/items/{vid}/pin",
        json={"pinned": True},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "已钉住 西湖"
    assert _visit(data, "西湖")["pinned"] is True
    resp = client.post(
        f"/api/v1/plan/{body['session_id']}/items/{vid}/pin",
        json={"pinned": False},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "已取消钉住 西湖"
    assert _visit(data, "西湖")["pinned"] is False


def test_pin_guard_chain_400_404():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海"], "days": 1, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    # missing device header
    resp = client.post(f"/api/v1/plan/{sid}/items/v1/pin", json={"pinned": True})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "missing_device_id"}
    # foreign/unknown session
    resp = client.post(
        "/api/v1/plan/no-such/items/v1/pin",
        json={"pinned": True},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session_not_found"}
    # unknown item
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v_none/pin",
        json={"pinned": True},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "item_not_found"}


def test_pin_requires_time_returns_422():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    app = make_app(agent)
    store = app.dependency_overrides[get_plan_sessions]()
    client = TestClient(app)
    body = start(
        client, {"cities": ["上海"], "days": 1, "preferences": "博物馆"}
    ).json()
    session = store.get(body["session_id"], device_id="device-1")
    item = next(
        i for d in session.plan.days for i in d.items if isinstance(i, VisitItem)
    )
    item.start_time = None
    item.end_time = None
    resp = client.post(
        f"/api/v1/plan/{body['session_id']}/items/{item.item_id}/pin",
        json={"pinned": True},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "pinned_requires_time"}


def test_delete_removes_pinned_item_and_marks_unwanted():
    svc = UnwantRecorder()
    agent = PlanningAgent(StubAdapter([V0_JSON]), trip_items=svc)
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid, iid = body["session_id"], body["plan"]["itinerary_id"]
    vid = _visit(body, "雷峰塔")["item_id"]
    pinned = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/pin",
        json={"pinned": True},
        headers=DEVICE_HEADERS,
    )
    assert pinned.status_code == 200
    resp = client.post(f"/api/v1/plan/{sid}/items/{vid}/delete", headers=DEVICE_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    names = [i.get("name") for d in data["plan"]["days"] for i in d["items"]]
    assert "雷峰塔" not in names  # pinned item is NOT blocked by rule 19
    assert data["reply"] == "已删除 雷峰塔，已记入不想去"
    assert svc.calls == [("雷峰塔", iid, "杭州")]


def test_delete_guard_chain_400_404():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海"], "days": 1, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    resp = client.post(f"/api/v1/plan/{sid}/items/v1/delete")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "missing_device_id"}
    resp = client.post("/api/v1/plan/no-such/items/v1/delete", headers=DEVICE_HEADERS)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v_none/delete", headers=DEVICE_HEADERS
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "item_not_found"}


# --- POST /plan/{id}/items/{item_id}/move（2026-10-24 规划页拖拽）-----------


def _append_day1_visit(session, item_id: str, name: str, h: int, m: int, dur: int):
    from datetime import time as dtime

    day1 = next(d for d in session.plan.days if d.day == 1)
    day1.items.append(
        VisitItem(
            item_id=item_id,
            name=name,
            city="杭州",
            day=1,
            start_time=dtime(h, m),
            end_time=dtime(h + dur // 60, m + dur % 60),
            duration_minutes=dur,
        )
    )


def _day_visits(body: dict, day_no: int) -> list[dict]:
    day = next(d for d in body["plan"]["days"] if d["day"] == day_no)
    return [i for i in day["items"] if "mode" not in i]


def test_move_same_day_reorder_resequences_times():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    app = make_app(agent)
    client = TestClient(app)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    store = app.dependency_overrides[get_plan_sessions]()
    session = store.get(sid, device_id="device-1")
    _append_day1_visit(session, "v2", "灵隐寺", 13, 0, 90)
    _append_day1_visit(session, "v3", "河坊街", 16, 0, 60)
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v3/move",
        json={"day": 1, "after_item_id": "v1"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    visits = _day_visits(data, 1)
    assert [v["item_id"] for v in visits] == ["v1", "v3", "v2"]
    slots = [(v["start_time"], v["end_time"]) for v in visits]
    assert all(s[0] and s[1] for s in slots)  # 全部重排后有时间
    assert all(a[1] <= b[0] for a, b in zip(slots, slots[1:]))  # 时链单调不重叠


def test_move_cross_day_to_head():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v2/move",
        json={"day": 1, "after_item_id": None},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert _visit(data, "雷峰塔")["day"] == 1
    assert not _day_visits(data, 2)  # 原天不再有景点
    names1 = [v["item_id"] for v in _day_visits(data, 1)]
    assert names1 == ["v2", "v1"]  # after=None → 插到当天第一个景点前
    slots = {
        v["item_id"]: (v["start_time"], v["end_time"]) for v in _day_visits(data, 1)
    }
    assert all(s[0] and s[1] for s in slots.values())
    assert slots["v2"][1] <= slots["v1"][0]  # 时链单调


def test_move_pinned_item_returns_422():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid, vid = body["session_id"], _visit(body, "西湖")["item_id"]
    pinned = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/pin",
        json={"pinned": True},
        headers=DEVICE_HEADERS,
    )
    assert pinned.status_code == 200
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/move",
        json={"day": 1, "after_item_id": None},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "pinned_locked"}


def test_move_guard_chain_400_404_422():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    resp = client.post(f"/api/v1/plan/{sid}/items/v1/move", json={"day": 1})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "missing_device_id"}
    resp = client.post(
        "/api/v1/plan/no-such/items/v1/move",
        json={"day": 1},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v_none/move",
        json={"day": 1},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "item_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v1/move",
        json={"day": 99},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "day_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v1/move",
        json={"day": 1, "after_item_id": "v_none"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "after_not_found"}


def test_fallback_sequence_keeps_list_order_then_sorts_by_time():
    """2026-10-24 拖拽回归：重排必须按列表顺序游标推进（后项不得回插到
    前项之前的空档），排完当天列表按 start_time 排序、无时间垫底。"""
    from datetime import time as dtime

    from app.services.agent.plan import _fallback_sequence_times
    from app.services.itinerary import DayPlan, ItineraryPlan, TransferItem

    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["成都"],
        days=[
            DayPlan(
                day=1,
                base_city="成都",
                items=[
                    TransferItem(
                        item_id="x1",
                        day=1,
                        seq=0,
                        from_city="重庆",
                        to_city="成都",
                        start_time=dtime(9, 35),
                        end_time=dtime(11, 17),
                    ),
                    VisitItem(
                        item_id="v1",
                        name="甲",
                        city="成都",
                        day=1,
                        duration_minutes=60,
                    ),
                    VisitItem(
                        item_id="v2",
                        name="乙",
                        city="成都",
                        day=1,
                        duration_minutes=120,
                    ),
                    VisitItem(
                        item_id="v3",
                        name="丙",
                        city="成都",
                        day=1,
                        duration_minutes=90,
                    ),
                    VisitItem(
                        item_id="v4",
                        name="夜游",
                        city="成都",
                        day=1,
                        start_time=dtime(16, 17),
                        end_time=dtime(17, 47),
                        duration_minutes=90,
                        pinned=True,
                    ),
                ],
            )
        ],
    )
    _fallback_sequence_times(plan)
    visits = [i for i in plan.days[0].items if not getattr(i, "from_city", None)]
    seq = [(v.name, v.start_time) for v in visits if v.start_time is not None]
    starts = [t for _, t in seq]
    assert starts == sorted(starts)  # 展示顺序=时间顺序
    assert seq[0] == ("甲", dtime(12, 47))  # 首个空档（高铁 11:17+90min 缓冲）
    assert seq[1] == ("夜游", dtime(16, 17))  # pinned 锚点
    assert seq[2] == ("乙", dtime(18, 17))  # 塞不进夜游前空档 → 排到夜游后
    assert visits[-1].name == "丙" and visits[-1].start_time is None  # 排不下垫底


# --- POST /plan/{id}/items/{item_id}/retime（2026-10-24 点时间戳改时间）-----


def test_retime_sets_anchor_and_resequences_day():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    app = make_app(agent)
    client = TestClient(app)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    store = app.dependency_overrides[get_plan_sessions]()
    session = store.get(sid, device_id="device-1")
    _append_day1_visit(session, "v2", "灵隐寺", 13, 0, 90)
    _append_day1_visit(session, "v3", "河坊街", 16, 0, 60)
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v3/retime",
        json={"start_time": "13:30"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    v3 = _visit(data, "河坊街")
    assert v3["start_time"] == "13:30:00"
    assert v3["end_time"] == "14:30:00"
    visits = _day_visits(data, 1)
    starts = [v["start_time"] for v in visits if v["start_time"]]
    assert starts == sorted(starts)  # 当天展示顺序=时间顺序
    assert all(v["start_time"] for v in visits)  # 其余景点全部重排出时间


def test_retime_on_pinned_allowed():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid, vid = body["session_id"], _visit(body, "西湖")["item_id"]
    pinned = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/pin",
        json={"pinned": True},
        headers=DEVICE_HEADERS,
    )
    assert pinned.status_code == 200
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/retime",
        json={"start_time": "13:30"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    v1 = _visit(resp.json(), "西湖")
    assert v1["start_time"] == "13:30:00"
    assert v1["pinned"] is True


def test_retime_guard_chain_400_404():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v1/retime", json={"start_time": "13:30"}
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "missing_device_id"}
    resp = client.post(
        "/api/v1/plan/no-such/items/v1/retime",
        json={"start_time": "13:30"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v_none/retime",
        json={"start_time": "13:30"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "item_not_found"}


# --- 条目变更触发实测腿刷新（用户拍板 2026-10-28）--------------------------


class _FakeWalkingAmap:
    """Only walking_route; every other amap surface degrades like None."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._n = 0

    async def walking_route(
        self, origin: str, destination: str, origin_id=None, destination_id=None
    ):
        self.calls.append((origin, destination))
        return {"distance_m": 1200, "duration_s": 900, "steps": [], "polyline": []}

    async def search_poi(self, name: str, city=None):
        self._n += 1
        return [
            {
                "source": "baidu",
                "source_poi_id": f"uid-{self._n}",
                "name": name,
                "city": city or "上海",
                "category": "景点",
                "address": "",
                "location": {"lon": 121.4 + 0.01 * self._n, "lat": 31.2},
            }
        ]


def test_item_mutations_trigger_leg_refresh():
    """pin/retime/move/delete 每个条目变更端点都必须调用 refresh_legs。"""
    agent = PlanningAgent(StubAdapter([V0_JSON] * 4))
    calls: list[str] = []

    async def _spy(session) -> None:
        calls.append("refresh")

    agent.refresh_legs = _spy  # type: ignore[method-assign]
    client = client_for(agent)
    prefs = {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}

    def new_session():
        b = start(client, prefs).json()
        return b["session_id"], _visit(b, "西湖")["item_id"]

    sid, vid = new_session()
    assert (
        client.post(
            f"/api/v1/plan/{sid}/items/{vid}/pin",
            json={"pinned": True},
            headers=DEVICE_HEADERS,
        ).status_code
        == 200
    )
    sid, vid = new_session()
    assert (
        client.post(
            f"/api/v1/plan/{sid}/items/{vid}/retime",
            json={"start_time": "09:00"},
            headers=DEVICE_HEADERS,
        ).status_code
        == 200
    )
    sid, vid = new_session()
    assert (
        client.post(
            f"/api/v1/plan/{sid}/items/{vid}/move",
            json={"day": 2, "after_item_id": None},
            headers=DEVICE_HEADERS,
        ).status_code
        == 200
    )
    sid, vid = new_session()
    assert (
        client.post(
            f"/api/v1/plan/{sid}/items/{vid}/delete", headers=DEVICE_HEADERS
        ).status_code
        == 200
    )
    assert len(calls) == 4


def test_refresh_legs_measures_new_pairs_after_move():
    """移动产生的新同日相邻对在响应里就带高德实测腿（leg_source=amap）。"""
    from app.services.itinerary.models import GeoPoint

    agent = PlanningAgent(StubAdapter([V0_JSON]))
    fake = _FakeWalkingAmap()
    agent._amap = fake  # type: ignore[assignment]
    app = make_app(agent)
    client = TestClient(app)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    store = app.dependency_overrides[get_plan_sessions]()
    session = store.get(sid, device_id="device-1")
    assert session is not None and session.plan is not None
    n = 0
    for day in session.plan.days:
        for it in day.items:
            if isinstance(it, VisitItem) and it.location is None:
                it.location = GeoPoint(lon=120.15 + 0.05 * n, lat=30.25)
                n += 1
    store.save(session)

    vid = _visit(body, "西湖")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/move",
        json={"day": 2, "after_item_id": None},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    assert fake.calls, "new same-day pair must be measured via amap"
    visits = [
        i for d in resp.json()["plan"]["days"] for i in d["items"] if "mode" not in i
    ]
    measured = [v for v in visits if v.get("leg_source") == "amap"]
    assert measured, "the new pair must carry a measured leg"
    assert measured[0]["distance_to_next_km"] == 1.2
    assert measured[0]["next_walk_minutes"] == 15


def test_refresh_legs_backfills_missing_locations():
    """旧行程条目缺坐标（loc=None）→ 变更时先回填坐标再实测腿。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    fake = _FakeWalkingAmap()
    agent._amap = fake  # type: ignore[assignment]
    app = make_app(agent)
    client = TestClient(app)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    vid = _visit(body, "西湖")["item_id"]
    # 前置：强制清空坐标模拟旧行程（生成期可能已回填）
    store = app.dependency_overrides[get_plan_sessions]()
    session = store.get(sid, device_id="device-1")
    assert session is not None and session.plan is not None
    for day in session.plan.days:
        for it in day.items:
            if isinstance(it, VisitItem):
                it.location = None
    store.save(session)

    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/move",
        json={"day": 2, "after_item_id": None},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    visits = [
        i for d in resp.json()["plan"]["days"] for i in d["items"] if "mode" not in i
    ]
    assert visits and all(v.get("location") for v in visits), (
        "backfill must fill coordinates for every missing item"
    )
    measured = [v for v in visits if v.get("leg_source") == "amap"]
    assert measured, "backfilled pair must carry a measured leg"


def test_get_plan_session_returns_refreshed_plan():
    """GET /plan/{id}：读路径也跑实测腿刷新——刷新页面即有距离/步行。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    fake = _FakeWalkingAmap()
    agent._amap = fake  # type: ignore[assignment]
    app = make_app(agent)
    client = TestClient(app)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    # 前置：强制清空坐标模拟旧行程
    store = app.dependency_overrides[get_plan_sessions]()
    session = store.get(sid, device_id="device-1")
    assert session is not None and session.plan is not None
    for day in session.plan.days:
        for it in day.items:
            if isinstance(it, VisitItem):
                it.location = None
    store.save(session)

    resp = client.get(f"/api/v1/plan/{sid}", headers=DEVICE_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "ready" and data["plan"]["days"]
    visits = [i for d in data["plan"]["days"] for i in d["items"] if "mode" not in i]
    assert visits and all(v.get("location") for v in visits), (
        "GET must backfill missing coordinates"
    )


def test_get_plan_session_guards():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    assert client.get("/api/v1/plan/no-such", headers=DEVICE_HEADERS).status_code == 404
    assert client.get("/api/v1/plan/x").status_code == 400


@pytest.fixture(autouse=True)
def _llm_select_mode():
    """本文件守护 LLM 选点（备用模式）语义；算法主路径见 test_algo_v0.py。"""
    os.environ["PLAN_SELECT_MODE"] = "llm"
    yield
    os.environ.pop("PLAN_SELECT_MODE", None)
