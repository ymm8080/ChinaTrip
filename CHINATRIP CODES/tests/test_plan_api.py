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

from app.api.amap import get_search_chain
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
    PlanSession,
    PlanSessionStore,
    _normalize_city,
    _parse_cities,
)
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.gate import RequestGate
from app.services.itinerary import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.itinerary_store import InMemoryItineraryStore
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import LLMError
from app.services.poi_details import PoiDetailStore

DEVICE_HEADERS = {"X-Device-ID": "device-1"}

V0_JSON = json.dumps(
    {
        "items": [
            # 75' 轻点（2026-11-04 大点闸：>80min 最晚 15:30 开场，day1
            # 13:14 抵 +150 地板=15:44 起排装不下 120' 大点→会被丢弃）——
            # V0 保住 day1 落点位，供 pin/move/replace 机制用例引用。
            {
                "name": "西湖",
                "city": "杭州",
                "category": "sight",
                "day": 1,
                "duration_minutes": 75,
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
    # 开放行程（结束城市杭州=终点）只有去程段；去程优先飞机（2026-11-04 拍板）
    assert modes == ["flight"]


def test_start_intercity_mode_stored_and_invalid_rejected():
    """2026-11-07 拍板：起始页交通选择落会话（全程城际段统一口径，后续
    重排路径经 session.intercity_mode 自动沿用）；非法值被 Literal 契约挡 422。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    app = make_app(agent)
    store = app.dependency_overrides[get_plan_sessions]()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/plan/start",
        json={
            "cities": ["上海", "杭州"],
            "days": 3,
            "preferences": "喜欢走路",
            "intercity_mode": "train",
        },
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    assert store.get(sid, device_id="device-1").intercity_mode == "train"
    bad = client.post(
        "/api/v1/plan/start",
        json={"cities": ["上海", "杭州"], "days": 3, "intercity_mode": "ship"},
        headers=DEVICE_HEADERS,
    )
    assert bad.status_code == 422


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
    # 结束城市杭州=行程终点（2026-11-13 起开放行程不自动回家）：第3天是
    # 完整活动日，挪过来的点直接落在当天，不再有返程腿占晚窗。
    day2 = [i for i in body["plan"]["days"][1]["items"] if i["item_id"] == "v2"]
    day3 = [i for i in body["plan"]["days"][2]["items"] if i["item_id"] == "v2"]
    assert day3 and not day2
    assert not any("mode" in i for i in body["plan"]["days"][2]["items"])


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
                # poi id 随关键词走：自动午餐搜索与必吃店名检索是不同店
                "source_poi_id": f"F-{keywords}",
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


class BriefPoiStore(PoiDetailStore):
    """底库桩：名字匹配不命中，candidate_by_name 直接落地（简报/图片读点用）。"""

    def __init__(self) -> None:
        super().__init__()

    def match_text_names(self, city, text, *, limit=8):
        return []

    def candidate_by_name(self, city, name):
        return {"name": name, "city": city, "category": "sight"}


def test_start_brief_opens_sites_confirm_round():
    from app.services.trip_items import TripItemService

    svc = TripItemService()
    brief = (
        "北京两日慢慢逛：第一天想去天坛和颐和园，第二天逛逛胡同和博物馆，"
        "喜欢历史建筑和本地小吃，节奏不要太赶，晚上想看夜景，"
        "住宿想住在二环里，交通尽量坐地铁，最后一天想买点伴手礼带回家。"
    )
    assert len(brief) >= 80  # 短句不读（_MIN_BRIEF_LLM_TEXT）
    sites = json.dumps(
        {
            "sites": [
                {"name": "天坛", "kind": "sight", "city": "北京", "day": 1},
                {"name": "颐和园", "kind": "sight", "city": "北京", "day": 2},
            ]
        },
        ensure_ascii=False,
    )
    agent = PlanningAgent(
        StubAdapter([sites, V0_JSON]),
        amap_client=NoPoiAmap(),
        poi_details=BriefPoiStore(),
        trip_items=svc,
    )
    client = client_for(agent)
    body = start(
        client,
        {"cities": ["北京"], "days": 2, "preferences": "历史建筑", "brief": brief},
    ).json()

    # 先问确认，不出行程、不入库
    assert body["state"] == "site_confirm"
    assert body["sites"] == ["天坛", "颐和园"]
    assert body["sites_source"] == "brief"
    assert "plan" not in body
    assert svc.list_groups()["wishlist"] == []

    sid = body["session_id"]
    r = client.post(
        f"/api/v1/plan/{sid}/sites/confirm",
        json={"mandatory": ["天坛"]},
        headers=DEVICE_HEADERS,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "ready"
    assert data["plan"] is not None
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["天坛"]
    assert "你确认的" in data["reply"]


class VisionStubAdapter(StubAdapter):
    """文字回复照旧，多一个 chat_vision 供图片读点。"""

    def __init__(self, replies: list[str], vision_reply: str) -> None:
        super().__init__(replies)
        self.vision_reply = vision_reply

    async def chat_vision(self, images, prompt: str) -> str:
        return self.vision_reply


def test_images_endpoint_opens_site_round():
    from app.services.trip_items import TripItemService

    svc = TripItemService()
    agent = PlanningAgent(
        VisionStubAdapter(
            [V0_JSON],
            json.dumps(
                {"sites": [{"name": "天坛", "kind": "sight", "city": "北京"}]},
                ensure_ascii=False,
            ),
        ),
        amap_client=NoPoiAmap(),
        poi_details=BriefPoiStore(),
        trip_items=svc,
    )
    client = client_for(agent)
    started = start(
        client, {"cities": ["北京"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = started["session_id"]

    r = client.post(
        f"/api/v1/plan/{sid}/images",
        files={"files": ("note.png", b"\x89PNG\r\n", "image/png")},
        headers=DEVICE_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "site_confirm"
    assert body["sites"] == ["天坛"]
    assert body["sites_source"] == "image"
    assert svc.list_groups()["wishlist"] == []  # 确认前不入库

    r = client.post(
        f"/api/v1/plan/{sid}/sites/confirm",
        json={"mandatory": ["天坛"]},
        headers=DEVICE_HEADERS,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "ready"
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["天坛"]


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


# --- 新行程简报：「重新规划」不再回到上次行程（2026-11-13）----------------


def test_trip_brief_parser_separates_new_trip_from_edit():
    from app.services.agent.plan import _is_new_trip_request, _trip_brief

    # 整趟行程（起止两城 + 天数）：新行程
    assert _trip_brief("从北京出发，去成都玩3天") == (["北京", "成都"], 3)
    assert _is_new_trip_request("从北京出发，去成都玩3天")
    # 单城 + 重开语气：也算新行程
    assert _is_new_trip_request("重新规划：成都 3 天")
    # 改当前行程的话术不得被误判成换行程
    assert not _is_new_trip_request("把雷峰塔挪到第三天")
    assert not _is_new_trip_request("加一天，去苏州玩")
    assert not _is_new_trip_request("外滩怎么走")


def test_message_new_trip_brief_restarts_and_leaves_old_itinerary_untouched():
    """✏️ 修改会话里说出另一趟完整行程：后端重开新会话，旧行程不动。

    2026-11-13 事故：旧逻辑按修改回合处理，把「去成都玩3天」当成景点塞进
    上海行程第 1 天，用户看到的就是「重新规划又回到上次行程」。
    """
    agent = PlanningAgent(StubAdapter([V0_JSON, V0_JSON]))
    app = make_app(agent)
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
    loaded = client.post(
        f"/api/v1/plan/from-itinerary/{iid}", json={}, headers=DEVICE_HEADERS
    ).json()
    resp = message(client, loaded["session_id"], "从北京出发，去成都玩3天")
    assert resp.status_code == 200
    body = resp.json()
    # 换局：新 session_id + 新路线，绝不是旧会话的又一个版本
    assert body["session_id"] and body["session_id"] != loaded["session_id"]
    assert body["new_trip"] is True
    assert body["plan"]["cities"] == ["北京", "成都"]
    assert len(body["plan"]["days"]) == 3
    assert body["plan"]["itinerary_id"] != iid
    # 旧行程原样：工作版本与快照都没被这轮对话改过
    rec = client.get(f"/api/v1/itineraries/{iid}", headers=DEVICE_HEADERS).json()
    assert rec["plan"]["cities"] == ["上海", "杭州"]
    assert rec["working_sync_version"] == 1
    assert len(rec["snapshots"]) == 1


def test_message_edit_wording_does_not_restart_session():
    agent = PlanningAgent(StubAdapter([V0_JSON, EDIT_JSON]))
    client = client_for(agent)
    sid = start(
        client, {"cities": ["上海", "杭州"], "days": 3, "preferences": "博物馆"}
    ).json()["session_id"]
    body = message(client, sid, "加一天，去苏州玩").json()
    assert body["session_id"] == sid  # 同一个会话：这是改行程，不是换行程
    assert not body.get("new_trip")


def test_start_brief_overrides_prefilled_form_route():
    """「重新规划」把上次参数回填进表单后，自由输入那句才是新设置：
    文字与表单不一致先出 confirm_route，用户选文字（route_source=brief）
    后按简报路线生成（2026-11-14 用户拍板「冲突必须确认」）。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client,
        {
            "cities": ["上海", "杭州"],
            "days": 3,
            "preferences": "博物馆",
            "brief": "从北京出发，去成都玩2天",
        },
    ).json()
    assert body["state"] == "confirm_route"
    assert body["text_route"]["cities"] == ["北京", "成都"]
    assert body["text_route"]["days"] == 2
    body = start(
        client,
        {
            "cities": ["上海", "杭州"],
            "days": 3,
            "preferences": "博物馆",
            "brief": "从北京出发，去成都玩2天",
            "route_source": "brief",
        },
    ).json()
    assert body["plan"]["cities"] == ["北京", "成都"]
    assert len(body["plan"]["days"]) == 2


def test_start_brief_single_city_keeps_form_origin():
    """简报只报目的地：confirm 后选文字，出发城沿用表单（北京→成都）。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client,
        {
            "cities": ["北京", "上海"],
            "days": 2,
            "preferences": "博物馆",
            "brief": "成都2天",
        },
    ).json()
    assert body["state"] == "confirm_route"
    assert body["text_route"]["cities"] == ["北京", "成都"]
    body = start(
        client,
        {
            "cities": ["北京", "上海"],
            "days": 2,
            "preferences": "博物馆",
            "brief": "成都2天",
            "route_source": "brief",
        },
    ).json()
    assert body["plan"]["cities"] == ["北京", "成都"]


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

    def list_groups(
        self, itinerary_id: str | None = None, owner_device_id: str | None = None
    ) -> dict:
        return {"wishlist": [], "scheduled": [], "booked": [], "unwanted": []}

    def mark_unwanted(self, name, *, itinerary_id=None, city=None):
        self.calls.append((name, itinerary_id, city))
        return {"name": name, "status": "unwanted"}

    def mark_excluded(
        self,
        name,
        *,
        itinerary_id=None,
        city=None,
        draft_session_id=None,
        owner_account_id=None,
    ):
        # 2026-11-13 拍板：删站点 = 回心愿单 + EXCLUSION（同一处记账）
        self.calls.append((name, itinerary_id, city))
        return {"name": name, "status": "wishlist", "exclusion_flag": True}


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


def _append_visit(session, day: int, item_id: str, name: str, h: int, m: int, dur: int):
    from datetime import time as dtime

    target = next(d for d in session.plan.days if d.day == day)
    target.items.append(
        VisitItem(
            item_id=item_id,
            name=name,
            city="杭州",
            day=day,
            start_time=dtime(h, m),
            end_time=dtime(h + dur // 60, m + dur % 60),
            duration_minutes=dur,
        )
    )


def _day_visits(body: dict, day_no: int) -> list[dict]:
    day = next(d for d in body["plan"]["days"] if d["day"] == day_no)
    # 午饭占位件是餐窗不是景点（2026-10-31 午餐保底）：行程形状断言排除
    return [
        i
        for i in day["items"]
        if (
            "mode" not in i
            and not i.get("item_id", "").startswith("food-lunch-ph")
            # 酒店入住卡/每晚酒店卡/次日晨卡无坐标/不回填（2026-11-01/11-07/11-13）
            and not i.get("item_id", "").startswith("hotel-checkin")
            and not i.get("item_id", "").startswith("hotel-night")
            and not i.get("item_id", "").startswith("hotel-morning")
        )
    ]


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
    # 08:00 火车闸（2026-11-03）：day1 火车改 12:10-13:14 抵，落地后仅容
    # 一个白天点——同日重排机制改挂无转场的 day2 全天验证。
    _append_visit(session, 2, "v4", "灵隐寺", 13, 0, 90)
    _append_visit(session, 2, "v5", "河坊街", 16, 0, 60)
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v5/move",
        json={"day": 2, "after_item_id": "v2"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    visits = _day_visits(data, 2)
    # 2026-11-13 拍板「未安排（无时刻灰卡）不显示」：灵隐寺过正午闸留空
    # 披露后是无时刻非钉卡——下发响应剔除（内部工作副本原样保留，见下）。
    assert [v["item_id"] for v in visits] == ["v2", "v5"]
    slots = [(v["start_time"], v["end_time"]) for v in visits]
    # 离城日上午闸（2026-11-03 拍板）：days=2 时 day2 是 17:00 返程日——
    # 挪头重排后晨窗装 v2+v5（10:30 起是腿垫非游标跳，闸天不跳 12 点），
    # 灵隐寺 90 分钟 11:30 起 13:00 收尾过正午闸→留空披露，不塞午后。
    assert slots[0][0] and slots[0][1] <= "12:00:00"
    assert slots[1][0] and slots[1][1] <= "12:00:00"
    assert slots[1][0] >= slots[0][1]  # 时链单调不重叠
    # 出口过滤只动下发层：会话工作副本里 v4 仍是无时刻卡，重排/清算照管
    saved = store.get(sid, device_id="device-1")
    v4 = next(
        i
        for d in saved.plan.days
        for i in d.items
        if getattr(i, "item_id", None) == "v4"
    )
    assert v4.start_time is None and v4.end_time is None


def test_move_cross_day_to_head():
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    # 08:00 火车闸（2026-11-03）：day1 落地后仅容一个点，跨天挪头改挂
    # day1→day2 方向（西湖挪去 day2 头部）。
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v1/move",
        json={"day": 2, "after_item_id": None},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert _visit(data, "西湖")["day"] == 2
    assert not _day_visits(data, 1)  # 原天不再有景点
    names2 = [v["item_id"] for v in _day_visits(data, 2)]
    assert names2 == ["v1", "v2"]  # after=None → 插到当天第一个景点前
    slots = {
        v["item_id"]: (v["start_time"], v["end_time"]) for v in _day_visits(data, 2)
    }
    # 离城日上午闸（2026-11-03 拍板）：days=2 时 day2 是 17:00 返程日，
    # 景点都须正午闸前收尾；西湖缩 75'（2026-11-04 大点闸 fixture 适配）
    # 后 9:00-10:15+腿垫，雷峰塔 60' 也排进晨窗成时链。
    assert slots["v1"][0] and slots["v1"][1] <= "12:00:00"
    assert slots["v2"][0] and slots["v2"][1] <= "12:00:00"
    assert slots["v2"][0] >= slots["v1"][1]  # 时链单调不重叠


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
                        start_time=dtime(17, 17),
                        end_time=dtime(18, 47),
                        duration_minutes=90,
                        pinned=True,
                    ),
                ],
            )
        ],
    )
    # 拖拽权威路径语义（10-24）：keep_list_order=True 保护列表顺序游标
    # （引擎自动路径的 11-04 大点先排排序见 test_big_afternoon_rules）。
    _fallback_sequence_times(plan, keep_list_order=True)
    visits = [i for i in plan.days[0].items if not getattr(i, "from_city", None)]
    seq = [(v.name, v.start_time) for v in visits if v.start_time is not None]
    starts = [t for _, t in seq]
    assert starts == sorted(starts)  # 展示顺序=时间顺序
    # 2026-11-01 落地首停：高铁到达侧首个观光 ≥ 落地+150（原 +90）
    assert seq[0] == ("甲", dtime(13, 47))  # 首个空档（高铁 11:17+150min 地板）
    assert seq[1] == ("丙", dtime(15, 17))  # 甲+30 腿游标
    assert seq[2] == ("夜游", dtime(17, 17))  # pinned 锚点
    # 2026-11-07 开场闸 16:00（大点 15:30 带）：乙 120min 甲+30 腿
    # 15:17 起 ≤ 15:30 但 17:17 收尾撞夜游钉（±30 腿垫）→ 顺延越带留空；
    # 丙 90min 15:17-16:47 恰贴夜游腿垫前 → 合法。夜游（pinned）不受闸。
    untimed = [v.name for v in visits if v.start_time is None]
    assert untimed == ["乙"]


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
    # 08:00 火车闸（2026-11-03）：day1 落地后只剩半个下午，锚点改挂
    # 无转场的 day2。
    _append_visit(session, 2, "v4", "河坊街", 16, 0, 60)
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v4/retime",
        json={"start_time": "13:30"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    v4 = _visit(data, "河坊街")
    assert v4["start_time"] == "13:30:00"
    assert v4["end_time"] == "14:30:00"
    visits = _day_visits(data, 2)
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
    # 前置：强制清空坐标模拟旧行程（生成期可能已回填）；days=2 时 day2
    # 是 17:00 返程日——离城日上午闸（2026-11-03）下两点都须正午闸前
    # 收尾才能成对实测；V0 西湖已缩 75' 轻点（2026-11-04 大点闸），此处
    # 再压 60' 保险让 pair 挤进同一晨窗。
    store = app.dependency_overrides[get_plan_sessions]()
    session = store.get(sid, device_id="device-1")
    assert session is not None and session.plan is not None
    for day in session.plan.days:
        for it in day.items:
            if isinstance(it, VisitItem):
                it.location = None
                if it.item_id == vid:
                    it.duration_minutes = 60
    store.save(session)

    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/move",
        json={"day": 2, "after_item_id": None},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    visits = [
        i
        for d in resp.json()["plan"]["days"]
        for i in d["items"]
        if "mode" not in i
        # 午饭占位件无 POI 可回填（设计上不烧配额，2026-10-31）；酒店
        # 入住卡/每晚酒店卡/次日晨卡同理（2026-11-01/11-07/11-13）
        and not str(i.get("item_id", "")).startswith("food-lunch-ph")
        and not str(i.get("item_id", "")).startswith("hotel-checkin")
        and not str(i.get("item_id", "")).startswith("hotel-night")
        and not str(i.get("item_id", "")).startswith("hotel-morning")
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
    visits = [
        i
        for d in data["plan"]["days"]
        for i in d["items"]
        if "mode" not in i
        # 午饭占位件无 POI 可回填（设计上不烧配额，2026-10-31）；酒店
        # 入住卡/每晚酒店卡/次日晨卡同理（2026-11-01/11-07/11-13）
        and not str(i.get("item_id", "")).startswith("food-lunch-ph")
        and not str(i.get("item_id", "")).startswith("hotel-checkin")
        and not str(i.get("item_id", "")).startswith("hotel-night")
        and not str(i.get("item_id", "")).startswith("hotel-morning")
    ]
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


# --- POST /plan/{id}/items/{item_id}/replace（2026-11-01 换景点：名字
# --- 可编辑，关键字去库里匹配；无匹配由 H5 引导留空）-----------------------


REPLACE_CAND = {
    "source_poi_id": "ct_杭州_9",
    "name": "灵隐寺",
    "city": "杭州市",
    "category": "attraction",
    "address": "法云弄1号",
    "opening_hours": "07:00-18:00",
    "name_en": "Lingyin Temple",
    "address_en": None,
    "intro_en": None,
    "opening_hours_en": None,
    "best_visit_time": "morning",
    "booking_url": None,
    "rain_ok": "yes",
    "rating": 4.7,
    "tags": ["4a"],
    # 75'（2026-11-04 大点闸 >80min 最晚 15:30 开场）：day1 落点位 15:44
    # 档容不下 120'——换入点须同尺寸才留得下（下方断言同步 75）。
    "suggested_duration_min": 75,
    "reservation_required": None,
    "reservation_advance_days": None,
    "location": (120.0972, 30.2414),
    "source": "4a",
}

# 2026-11-07 熊猫谷案：库真身行（amap，都江堰玉堂，距基地 ~58km）
PANDA_VALLEY_CAND = {
    "source_poi_id": "amap_cd_panda_valley",
    "name": "熊猫谷",
    "city": "成都市",
    "category": "attraction",
    "address": "四川省成都市都江堰市玉堂街道",
    "opening_hours": "08:00-17:00",
    "name_en": "Dujiangyan Panda Valley",
    "address_en": None,
    "intro_en": None,
    "opening_hours_en": None,
    "best_visit_time": "morning",
    "booking_url": None,
    "rain_ok": "yes",
    "rating": 4.5,
    "tags": ["intl"],
    "suggested_duration_min": 120,
    "reservation_required": None,
    "reservation_advance_days": None,
    "location": (103.59896, 30.96554),
    "source": "amap",
}


class StubReplaceStore:
    """candidate_by_name 桩：名字→候选，未命中 None。start 路径的其它
    库读方法给空实现（本文件其余用例 poi_details=None 不走库）。"""

    def __init__(self, mapping: dict | None = None) -> None:
        self.mapping = mapping or {}
        self.calls: list = []

    def candidate_by_name(self, city, name):
        self.calls.append((city, name))
        return self.mapping.get(name)

    def db_degraded(self):
        return False

    def get(self, source_poi_id):
        return None

    def upsert(self, *a, **k):
        return None

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        return []

    def search_keyword(self, city, tokens, *, limit=5):
        return []

    def get_by_name(self, city, name):
        return None


def test_replace_swaps_item_in_place_and_retimes_day():
    store = StubReplaceStore({"灵隐寺": REPLACE_CAND})
    agent = PlanningAgent(StubAdapter([V0_JSON]), poi_details=store)
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    vid = _visit(body, "西湖")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/replace",
        json={"name": "灵隐寺"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    new = _visit(data, "灵隐寺")
    assert new["day"] == 1  # 原位：同天
    assert new["item_id"] != vid  # 新条目新 id
    assert new["poi_id"] == "ct_杭州_9"
    assert new["duration_minutes"] == 75
    assert new["location"]["lon"] == pytest.approx(120.0972)
    with pytest.raises(StopIteration):
        _visit(data, "西湖")  # 旧点不再出现
    assert store.calls == [("杭州", "灵隐寺")]  # 按条目所在城收窄
    slots = [(v["start_time"], v["end_time"]) for v in _day_visits(data, 1)]
    assert slots and all(s[0] and s[1] for s in slots)  # 当天时链完整


def test_replace_no_match_422():
    agent = PlanningAgent(StubAdapter([V0_JSON]), poi_details=StubReplaceStore())
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    vid = _visit(body, "西湖")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/replace",
        json={"name": "库里没有的点"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "no_match"}


def test_replace_duplicate_in_plan_422():
    cand = dict(REPLACE_CAND, name="雷峰塔", source_poi_id="ct_杭州_2")
    agent = PlanningAgent(
        StubAdapter([V0_JSON]), poi_details=StubReplaceStore({"雷峰塔": cand})
    )
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    vid = _visit(body, "西湖")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/replace",
        json={"name": "雷峰塔"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "duplicate_in_plan"}


def _panda_session():
    """成都日：基地+文殊院/剧院 真身坐标（替代组用例共用）。"""
    from app.services.agent.plan import PlanSession
    from app.services.itinerary.models import (
        DayPlan,
        GeoPoint,
        ItineraryPlan,
        VisitItem,
    )

    base = VisitItem(
        item_id="v1",
        name="成都大熊猫繁育研究基地",
        poi_id="amap:成都:熊猫基地",
        category="sight",
        city="成都",
        location=GeoPoint(lon=104.13953, lat=30.73945),
        day=1,
        duration_minutes=90,
    )
    other = VisitItem(
        item_id="v2",
        name="文殊院",
        poi_id="amap:成都:文殊院",
        category="sight",
        city="成都",
        location=GeoPoint(lon=104.0676, lat=30.6710),
        day=1,
        duration_minutes=60,
    )
    session = PlanSession(
        session_id="s-panda",
        device_id="device-1",
        plan=ItineraryPlan(
            itinerary_id="it-panda",
            cities=["成都"],
            days=[DayPlan(day=1, base_city="成都", items=[base, other])],
        ),
    )
    return session


def test_replace_substitute_of_planned_site_blocked():
    """2026-11-07 拍板「已经排熊猫基地，就不要排熊猫谷了」：行程已有
    基地时，给其它条目换入熊猫谷 = 同体验替代组撞 duplicate_in_plan
    （谷距基地 ~58km，旧查重 _same_site 名字互含拦不住）。换基地本人
    的正当替换不受影响（others 不含被换条目，见下方重排用例）。"""
    import asyncio

    store = StubReplaceStore({"熊猫谷": PANDA_VALLEY_CAND})
    agent = PlanningAgent(StubAdapter([]), poi_details=store)
    session = _panda_session()
    with pytest.raises(ValueError) as ei:
        asyncio.run(agent.replace_item(session, "v2", name="熊猫谷"))
    assert str(ei.value) == "duplicate_in_plan"
    # 行程未被改动
    names = [str(i.name) for i in session.plan.days[0].items]
    assert names == ["成都大熊猫繁育研究基地", "文殊院"]


def test_replace_far_swap_reorders_day_by_distance():
    """2026-11-07 拍板「熊猫谷替换熊猫基地」：换入点距原点位 ~58km，
    当天插入式重排按距离聚合（与 LNS _retime_trial 同口径，pinned/餐锚
    不动），并把重排写进变更摘要。列表序故意把近谷的离堆公园（~7km）
    压在队尾、58km 外的文殊院放中间——重排后离堆必须被聚到谷旁边，
    文殊院按距离让位其后。换入近点（<3km）不触发重排（近点用例见
    replace 原位套件）。"""
    import asyncio

    from app.services.itinerary.models import GeoPoint, VisitItem

    near_valley = PANDA_VALLEY_CAND  # 58km 触发重排
    store = StubReplaceStore({"熊猫谷": near_valley})
    agent = PlanningAgent(StubAdapter([]), poi_details=store)
    session = _panda_session()
    # 邻居不用熊猫苑（谷↔苑互为替代会被新闸拦下=规则生效）：
    # day1 = [基地(将换), 文殊院(城区,游时压短留闸余量), 离堆公园(近谷)]
    day = session.plan.days[0]
    day.items[1] = VisitItem(
        item_id="v2",
        name="文殊院",
        poi_id="amap:成都:文殊院",
        category="sight",
        city="成都",
        location=GeoPoint(lon=104.0676, lat=30.6710),
        day=1,
        duration_minutes=30,
    )
    duidui = VisitItem(
        item_id="v3",
        name="离堆公园",
        poi_id="amap:成都:离堆公园",
        category="sight",
        city="成都",
        location=GeoPoint(lon=103.6172, lat=31.0032),
        day=1,
        duration_minutes=75,
    )
    day.items.append(duidui)
    report, summary, notes = asyncio.run(
        agent.replace_item(session, "v1", name="熊猫谷")
    )
    # replace 走深拷贝（session.plan 换新对象），断言前重新取日
    day = session.plan.days[0]
    names = [str(i.name) for i in day.items]
    assert names == ["熊猫谷", "离堆公园", "文殊院"]  # 距离聚合：谷↔离堆相邻
    visits = [
        i for i in day.items if not str(getattr(i, "item_id", "")).startswith("food")
    ]
    assert all(v.start_time and v.end_time for v in visits)  # 时链完整
    assert any("按距离重新排列" in s for s in summary.change_summary)
    assert report.ok


def test_replace_near_swap_keeps_list_order():
    """同商圈换位（<3km）：不触发插入式重排，保持用户列表序（原位换入
    套件同款）。宽窄巷子↔人民公园 ~1.6km。"""
    import asyncio

    from app.services.agent.plan import PlanSession
    from app.services.itinerary.models import (
        DayPlan,
        GeoPoint,
        ItineraryPlan,
        VisitItem,
    )

    cand = {
        "source_poi_id": "amap_cd_kuanzhai",
        "name": "宽窄巷子",
        "city": "成都市",
        "category": "attraction",
        "opening_hours": "全天",
        "name_en": "Kuanzhai Alley",
        "address_en": None,
        "intro_en": None,
        "opening_hours_en": None,
        "best_visit_time": "any",
        "booking_url": None,
        "rain_ok": "yes",
        "rating": 4.4,
        "tags": [],
        "suggested_duration_min": 90,
        "reservation_required": None,
        "reservation_advance_days": None,
        "location": (104.0532, 30.6697),
        "source": "amap",
    }
    store = StubReplaceStore({"宽窄巷子": cand})
    agent = PlanningAgent(StubAdapter([]), poi_details=store)
    items = [
        VisitItem(
            item_id="v1",
            name="人民公园",
            poi_id="amap:成都:人民公园",
            category="sight",
            city="成都",
            location=GeoPoint(lon=104.0568, lat=30.6636),
            day=1,
            duration_minutes=60,
        ),
        VisitItem(
            item_id="v2",
            name="文殊院",
            poi_id="amap:成都:文殊院",
            category="sight",
            city="成都",
            location=GeoPoint(lon=104.0676, lat=30.6710),
            day=1,
            duration_minutes=60,
        ),
    ]
    session = PlanSession(
        session_id="s-near",
        device_id="device-1",
        plan=ItineraryPlan(
            itinerary_id="it-near",
            cities=["成都"],
            days=[DayPlan(day=1, base_city="成都", items=items)],
        ),
    )
    report, summary, _notes = asyncio.run(
        agent.replace_item(session, "v1", name="宽窄巷子")
    )
    names = [str(i.name) for i in session.plan.days[0].items]
    assert names == ["宽窄巷子", "文殊院"]  # 原位：列表序不动
    assert not any("按距离重新排列" in s for s in summary.change_summary)
    assert report.ok


def test_replace_meal_slot_locked_422():
    agent = PlanningAgent(
        StubAdapter([V0_JSON]),
        poi_details=StubReplaceStore({"灵隐寺": REPLACE_CAND}),
    )
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    meals = [
        i
        for d in body["plan"]["days"]
        for i in d["items"]
        if str(i.get("item_id", "")).startswith("food-lunch-ph")
    ]
    assert meals  # 前置：午餐占位存在
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{meals[0]['item_id']}/replace",
        json={"name": "灵隐寺"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "meal_slot_locked"}


def test_replace_pinned_item_allowed_and_fresh_unpinned():
    store = StubReplaceStore({"灵隐寺": REPLACE_CAND})
    agent = PlanningAgent(StubAdapter([V0_JSON]), poi_details=store)
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    vid = _visit(body, "西湖")["item_id"]
    assert (
        client.post(
            f"/api/v1/plan/{sid}/items/{vid}/pin",
            json={"pinned": True},
            headers=DEVICE_HEADERS,
        ).status_code
        == 200
    )
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{vid}/replace",
        json={"name": "灵隐寺"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200  # 用户显式动作最高优先（同 retime）
    new = _visit(resp.json(), "灵隐寺")
    assert new["pinned"] is False  # 新点不继承钉（用户可再钉）


def test_replace_guard_chain_400_404_422():
    agent = PlanningAgent(
        StubAdapter([V0_JSON]),
        poi_details=StubReplaceStore({"灵隐寺": REPLACE_CAND}),
    )
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    assert (
        client.post(
            f"/api/v1/plan/{sid}/items/v1/replace", json={"name": "灵隐寺"}
        ).status_code
        == 400
    )  # 缺 X-Device-ID
    assert (
        client.post(
            "/api/v1/plan/no-such/items/v1/replace",
            json={"name": "灵隐寺"},
            headers=DEVICE_HEADERS,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/plan/{sid}/items/v_none/replace",
            json={"name": "灵隐寺"},
            headers=DEVICE_HEADERS,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/plan/{sid}/items/v1/replace",
            json={"name": ""},
            headers=DEVICE_HEADERS,
        ).status_code
        == 422
    )


# --- POST /plan/{id}/items/{id}/set-hotel（2026-11-07 每晚酒店卡）----------


class _StubHotelChainClient:
    vendor = "stub"  # 独立 vendor 名：不碰共享配额闩（_SEARCH_LATCH）

    def __init__(self, hits=None):
        self._hits = (
            hits
            if hits is not None
            else [
                {
                    "source": "amap",
                    "source_poi_id": "B0H1",
                    "name": "全季酒店（西湖店）",
                    "city": "杭州",
                    "category": "住宿服务:酒店宾馆",
                    "address": "西湖区龙井路1号",
                    "location": {"lon": 120.13, "lat": 30.24},
                    "opening_hours": None,
                    "rating": "4.6",
                }
            ]
        )

    async def search_poi(self, keywords, *, city=None, page=1):
        return self._hits


def _hotel_session_app(chain=None):
    """直接造带夜卡的 ready 会话（不经 v0 build——最小隔离面）。"""
    from datetime import time as dtime

    agent = PlanningAgent(StubAdapter([]))
    app = make_app(agent)
    app.dependency_overrides[get_settings] = lambda: Settings(
        llm_backend="mock", amap_api_key="k", map_provider="amap"
    )
    app.dependency_overrides[get_search_chain] = lambda: (
        chain if chain is not None else []
    )
    store = app.dependency_overrides[get_plan_sessions]()
    night = VisitItem(
        item_id="hotel-night-d1",
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="杭州",
        day=1,
        start_time=dtime(20, 0),
        end_time=dtime(21, 0),
        duration_minutes=60,
        soft_pin=True,
    )
    visit = VisitItem(item_id="v1", name="西湖", category="sight", city="杭州", day=1)
    # 2026-11-13 每天出发点=HOTEL：次日晨卡与已排首站（set-hotel 双向同步面）
    morning = VisitItem(
        item_id="hotel-morning-d2",
        name="🏨 从酒店出发（今日起点）",
        category="hotel",
        city="杭州",
        day=2,
        start_time=dtime(8, 0),
        end_time=dtime(8, 30),
        duration_minutes=30,
        soft_pin=True,
    )
    visit2 = VisitItem(
        item_id="v2",
        name="灵隐寺",
        category="sight",
        city="杭州",
        day=2,
        start_time=dtime(9, 0),
        end_time=dtime(11, 0),
        duration_minutes=120,
        location=GeoPoint(lon=120.10, lat=30.24),
    )
    store.save(
        PlanSession(
            session_id="s-hotel",
            device_id="device-1",
            state="ready",
            plan=ItineraryPlan(
                itinerary_id="it-h",
                cities=["杭州"],
                days=[
                    DayPlan(day=1, base_city="杭州", items=[visit, night]),
                    DayPlan(day=2, base_city="杭州", items=[morning, visit2]),
                ],
            ),
        )
    )
    return app


def _hotel_item(body, item_id):
    return next(
        i
        for d in body["plan"]["days"]
        for i in d["items"]
        if i.get("item_id") == item_id
    )


def _night_item(body):
    return next(
        i
        for d in body["plan"]["days"]
        for i in d["items"]
        if i.get("item_id") == "hotel-night-d1"
    )


def test_set_hotel_writes_verified_fields_with_coords():
    app = _hotel_session_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-hotel/items/hotel-night-d1/set-hotel",
            json={
                "name": "酒店甲",
                "source_poi_id": "B0X",
                "address": "甲路1号",
                "opening_hours": "全天",
                "lon": 120.1,
                "lat": 30.2,
            },
            headers=DEVICE_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    card = _night_item(data)
    assert card["name"] == "酒店甲"
    assert card["address"] == "甲路1号"
    assert card["opening_hours"] == "全天"
    assert card["poi_id"] == "B0X"
    assert card["location"] == {"lon": 120.1, "lat": 30.2}
    assert "酒店甲" in data["reply"] and "甲路1号" in data["reply"]


def test_set_hotel_server_verifies_when_coords_missing():
    app = _hotel_session_app(chain=[_StubHotelChainClient()])
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-hotel/items/hotel-night-d1/set-hotel",
            json={"name": "全季"},
            headers=DEVICE_HEADERS,
        )
    assert resp.status_code == 200
    card = _night_item(resp.json())
    assert card["name"] == "全季酒店（西湖店）"
    assert card["address"] == "西湖区龙井路1号"
    assert card["poi_id"] == "B0H1"
    assert card["location"] == {"lon": 120.13, "lat": 30.24}


def test_set_hotel_no_match_422():
    app = _hotel_session_app(chain=[_StubHotelChainClient(hits=[])])
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-hotel/items/hotel-night-d1/set-hotel",
            json={"name": "不存在的酒店"},
            headers=DEVICE_HEADERS,
        )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "no_match"}


def test_set_hotel_not_hotel_slot_422():
    app = _hotel_session_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-hotel/items/v1/set-hotel",
            json={"name": "酒店甲", "lon": 120.1, "lat": 30.2},
            headers=DEVICE_HEADERS,
        )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "not_hotel_slot"}


def test_set_hotel_guard_chain_400_404():
    app = _hotel_session_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-hotel/items/hotel-night-d1/set-hotel",
            json={"name": "酒店甲"},
        )
        assert resp.status_code == 400
        assert resp.json() == {"detail": "missing_device_id"}
        resp = client.post(
            "/api/v1/plan/no-such/items/hotel-night-d1/set-hotel",
            json={"name": "酒店甲"},
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "session_not_found"}
        resp = client.post(
            "/api/v1/plan/s-hotel/items/v_none/set-hotel",
            json={"name": "酒店甲"},
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "item_not_found"}


# --- 每天出发点=HOTEL（2026-11-13）：夜卡 set-hotel 双向同步晨卡 ------------


def test_set_hotel_syncs_next_morning_card():
    """夜卡写入已验证酒店 → 次日晨卡继承名称/地址/坐标（同一段住宿）。"""
    app = _hotel_session_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-hotel/items/hotel-night-d1/set-hotel",
            json={
                "name": "酒店甲",
                "source_poi_id": "B0X",
                "address": "甲路1号",
                "lon": 120.10,
                "lat": 30.24,
            },
            headers=DEVICE_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    night = _hotel_item(data, "hotel-night-d1")
    morning = _hotel_item(data, "hotel-morning-d2")
    assert night["name"] == "酒店甲"
    assert morning["name"] == "🏨 从酒店出发（酒店甲）"
    assert morning["address"] == "甲路1号"
    assert morning["poi_id"] == "B0X"
    assert morning["location"] == {"lon": 120.10, "lat": 30.24}


def test_set_hotel_from_morning_syncs_previous_night():
    """晨卡 ✏️ 写入酒店 → 前一晚夜卡同步店名/坐标（反向一致）。"""
    app = _hotel_session_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-hotel/items/hotel-morning-d2/set-hotel",
            json={
                "name": "酒店乙",
                "source_poi_id": "B0Y",
                "address": "乙路2号",
                "lon": 120.10,
                "lat": 30.24,
            },
            headers=DEVICE_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    night = _hotel_item(data, "hotel-night-d1")
    morning = _hotel_item(data, "hotel-morning-d2")
    assert night["name"] == "酒店乙"
    assert night["address"] == "乙路2号"
    assert night["poi_id"] == "B0Y"
    assert morning["name"] == "🏨 从酒店出发（酒店乙）"
    assert morning["location"] == {"lon": 120.10, "lat": 30.24}


def _hotel_stay_app():
    """3 晚同城住宿（夜卡 d1/d2/d3 + 晨卡 d2/d3/d4）：整段铺开面。"""
    from datetime import time as dtime

    agent = PlanningAgent(StubAdapter([]))
    app = make_app(agent)
    app.dependency_overrides[get_settings] = lambda: Settings(
        llm_backend="mock", amap_api_key="k", map_provider="amap"
    )
    app.dependency_overrides[get_search_chain] = lambda: []
    store = app.dependency_overrides[get_plan_sessions]()
    days = []
    for no in (1, 2, 3):
        items = []
        if no > 1:
            items.append(
                VisitItem(
                    item_id=f"hotel-morning-d{no}",
                    name="🏨 从酒店出发（今日起点）",
                    category="hotel",
                    city="杭州",
                    day=no,
                    start_time=dtime(8, 0),
                    end_time=dtime(8, 30),
                    duration_minutes=30,
                    soft_pin=True,
                )
            )
        items.append(
            VisitItem(
                item_id=f"v{no}",
                name=f"景点{no}",
                category="sight",
                city="杭州",
                day=no,
                start_time=dtime(9, 0),
                end_time=dtime(11, 0),
                duration_minutes=120,
            )
        )
        items.append(
            VisitItem(
                item_id=f"hotel-night-d{no}",
                name="🏨 回酒店·夜间休息",
                category="hotel",
                city="杭州",
                day=no,
                start_time=dtime(20, 0),
                end_time=dtime(21, 0),
                duration_minutes=60,
                soft_pin=True,
            )
        )
        days.append(DayPlan(day=no, base_city="杭州", items=items))
    store.save(
        PlanSession(
            session_id="s-stay",
            device_id="device-1",
            state="ready",
            plan=ItineraryPlan(
                itinerary_id="it-s",
                cities=["杭州"],
                days=days,
            ),
        )
    )
    return app


def test_set_hotel_propagates_whole_stay():
    """一次 ✏️ 铺开整段住宿：同城连续夜的夜卡/晨卡都写上同一家酒店。"""
    app = _hotel_stay_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-stay/items/hotel-night-d1/set-hotel",
            json={
                "name": "酒店甲",
                "source_poi_id": "B0X",
                "address": "甲路1号",
                "lon": 120.10,
                "lat": 30.24,
            },
            headers=DEVICE_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    for no in (1, 2, 3):
        night = _hotel_item(data, f"hotel-night-d{no}")
        assert night["name"] == "酒店甲"
        assert night["poi_id"] == "B0X"
        assert night["address"] == "甲路1号"
    for no in (2, 3):
        morning = _hotel_item(data, f"hotel-morning-d{no}")
        assert morning["name"] == "🏨 从酒店出发（酒店甲）"
        assert morning["poi_id"] == "B0X"
    assert "已同步" in data["reply"]


def test_delete_night_card_removes_next_morning_card():
    """删夜卡=这一晚不住店：次日「从酒店出发」晨卡一并移除。"""
    app = _hotel_stay_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/plan/s-stay/items/hotel-night-d1/delete",
            headers=DEVICE_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    ids = [i.get("item_id") for d in data["plan"]["days"] for i in d["items"]]
    assert "hotel-night-d1" not in ids
    assert "hotel-morning-d2" not in ids
    assert "hotel-morning-d3" in ids
    assert "晨卡" in data["reply"]


def test_start_applies_intake_arrival_departure_times():
    """行前信息（2026-11-14 用户拍板）：/plan/start 带去程当地到达时刻与返程
    当地离开时刻 → v0 生成后按时刻落位对应城际腿（落地定去程腿 end，起飞/
    发车定返程腿 start），并在 assumptions 披露；会话字段落档供重建。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    store = None
    app = make_app(agent)
    store = app.dependency_overrides[get_plan_sessions]()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/plan/start",
        json={
            "cities": ["上海", "杭州"],
            "days": 3,
            "preferences": "喜欢走路",
            "arrival_time": "15:30",
            "departure_time": "16:00",
        },
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    plan = body["plan"]
    transfers = [
        it
        for d in plan["days"]
        for it in d["items"]
        if it.get("from_city") and it.get("to_city")
    ]
    assert transfers, "intercity legs expected in v0"
    outbound = min(transfers, key=lambda it: it["day"])
    inbound = max(transfers, key=lambda it: it["day"])
    assert outbound["end_time"].startswith("15:30")  # 当地落地
    assert inbound["start_time"].startswith("16:00")  # 无返程腿时补合成腿
    assert any("15:30" in a for a in body["assumptions"])
    sid = body["session_id"]
    session = store.get(sid, device_id="device-1")
    assert session.arrival_time == "15:30"
    assert session.departure_time == "16:00"


def test_route_conflict_between_text_and_form_asks_user():
    """文字说 2 天、表单 3 天：不静默裁决，返回 confirm_route 两边差异
    （2026-11-14 用户拍板「figure out diff for user confirmation」）。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    resp = start(
        client,
        {
            "cities": ["上海", "西安"],
            "days": 3,
            "preferences": "",
            "brief": "西安 2 天",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirm_route"
    assert body["text_route"]["cities"] == ["上海", "西安"]
    assert body["text_route"]["days"] == 2
    assert body["form_route"]["cities"] == ["上海", "西安"]
    assert body["form_route"]["days"] == 3


def test_route_conflict_user_picks_form():
    """确认卡选「按表单」：文字不再当简报改写路线，按表单参数生成。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    resp = start(
        client,
        {
            "cities": ["上海", "西安"],
            "days": 3,
            "preferences": "喜欢走路",
            "brief": "西安 2 天",
            "route_source": "form",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert body["plan"]["cities"] == ["上海", "西安"]
    assert len(body["plan"]["days"]) == 3


def test_route_conflict_user_picks_text():
    """确认卡选「按文字」：表单参数作废，路线全从文字解析。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    resp = start(
        client,
        {
            "cities": ["上海", "西安"],
            "days": 3,
            "preferences": "西安 2 天",
            "brief": "西安 2 天",
            "route_source": "brief",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert body["plan"]["cities"] == ["上海", "西安"]
    assert len(body["plan"]["days"]) == 2


def test_no_route_conflict_when_text_matches_form():
    """文字与表单一致（城市同、天数同）：不进确认，直接生成。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    resp = start(
        client,
        {
            "cities": ["上海", "杭州"],
            "days": 3,
            "preferences": "喜欢走路",
            "brief": "上海到杭州玩3天",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"


def test_route_days_diff_between_text_and_card_dates():
    """文字 2 天、行前卡日期跨度 4 天（表单天数与文字一致）：
    不静默裁决，confirm_route 摆出 days 差异（用户拍板③）。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    resp = start(
        client,
        {
            "cities": ["上海", "西安"],
            "days": 2,
            "preferences": "喜欢历史",
            "brief": "西安 2 天",
            "start_date": "2026-11-16",
            "arrival_date": "2026-11-16",
            "departure_date": "2026-11-19",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirm_route"
    whats = [d["what"] for d in body["diffs"]]
    assert "days" in whats
    days_diff = next(d for d in body["diffs"] if d["what"] == "days")
    assert days_diff["text"] == 2
    assert days_diff["intake"] == 4


def test_numbers_diff_between_text_and_card():
    """文字里有航班号、行前卡班次为空：confirm_route 摆出 numbers 差异。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    resp = start(
        client,
        {
            "cities": ["上海", "杭州"],
            "days": 3,
            "preferences": "喜欢走路",
            "brief": "乘CA1234去杭州玩3天",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirm_route"
    numbers = next(d for d in body["diffs"] if d["what"] == "numbers")
    assert numbers["text"] == ["CA1234"]
    assert numbers["intake"] == []


def test_days_override_applies_after_route_choice():
    """确认卡选边覆写：按表单路线但天数用文字的 2 天（days_override）。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    client = client_for(agent)
    resp = start(
        client,
        {
            "cities": ["上海", "西安"],
            "days": 3,
            "preferences": "喜欢历史",
            "brief": "西安 2 天",
            "route_source": "form",
            "days_override": 2,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert len(body["plan"]["days"]) == 2


def test_number_override_lands_on_session():
    """班次覆写落到会话（行前落位用它查班次/钉时刻）。"""
    agent = PlanningAgent(StubAdapter([V0_JSON]))
    app = make_app(agent)
    store = app.dependency_overrides[get_plan_sessions]()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/plan/start",
        json={
            "cities": ["上海", "杭州"],
            "days": 3,
            "preferences": "喜欢走路",
            "arrival_no_override": "G1234",
            "departure_no_override": "CA888",
        },
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    session = store.get(sid, device_id="device-1")
    assert session.arrival_no == "G1234"
    assert session.departure_no == "CA888"
