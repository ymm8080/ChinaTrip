"""行程契约场景测试（GET 出站闸级）：必去三分律披露 + unplaced 双在场清脏。

走真实 GET /api/v1/plan/{sid} 读闸（heal/审计/装配全链在跑），
会话手工构造——离线、确定性、不依赖 LLM/DB（照 test_leg_gap_heal 的
_StallSession 模式）。锚的是「契约」不是排期细节：选点/求解器在途重构
不应打破这三条出站不变量。
"""

from datetime import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.plan import get_plan_sessions, get_planning_agent, router
from app.services.agent.plan import PlanningAgent, PlanSession, PlanSessionStore
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    UnplacedCandidate,
    VisitItem,
)


class _NoLLMAdapter:
    name = "stub"

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("契约 GET 读闸不应调 LLM")


def _visit(iid, name, start=(9, 0), end=(10, 30), name_en=None):
    dur = (end[0] * 60 + end[1]) - (start[0] * 60 + start[1])
    return VisitItem(
        item_id=iid,
        name=name,
        name_en=name_en,
        city="上海",
        day=1,
        start_time=time(*start),
        end_time=time(*end),
        duration_minutes=dur,
    )


def _app_with(items, must, unplaced=None):
    agent = PlanningAgent(_NoLLMAdapter())

    async def _noop_refresh_legs(session):
        return None

    agent.refresh_legs = _noop_refresh_legs
    app = FastAPI()
    store = PlanSessionStore()
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: store
    app.include_router(router)
    session = PlanSession(
        session_id="s-ct",
        device_id="dev-1",
        state="ready",
        must_visits=list(must),
    )
    session.plan = ItineraryPlan(
        itinerary_id="it-ct",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=list(items))],
        assumptions=[],
        unplaced=list(unplaced or []),
    )
    store.save(session)
    return app, store


def _get(client):
    return client.get("/api/v1/plan/s-ct", headers={"X-Device-ID": "dev-1"})


def _stored(store):
    return store.get("s-ct", device_id="dev-1")


def test_missing_must_gets_disclosure_and_is_idempotent():
    app, store = _app_with([_visit("v1", "外滩")], must=["外滩", "豫园"])
    with TestClient(app) as client:
        r1 = _get(client)
        assert r1.status_code == 200
        r2 = _get(client)
        assert r2.status_code == 200
    stored = _stored(store)
    lines = [a for a in stored.plan.assumptions if "覆盖审计自动补记" in a]
    assert len(lines) == 1
    assert "豫园" in lines[0]
    # 响应本体就带披露（审计在 body 装配之前跑），不只落在库里
    resp_lines = [
        a for a in r1.json()["plan"]["assumptions"] if "覆盖审计自动补记" in a
    ]
    assert len(resp_lines) == 1


def test_scheduled_must_not_also_in_unplaced():
    unplaced = [
        UnplacedCandidate(name="上海中心大厦"),
        UnplacedCandidate(name="外滩源"),
    ]
    app, store = _app_with(
        [_visit("v1", "上海中心大厦")],
        must=["上海中心大厦", "外滩源"],
        unplaced=unplaced,
    )
    with TestClient(app) as client:
        r = _get(client)
    assert r.status_code == 200
    stored = _stored(store)
    # 双在场 chip 被清、合法 chip 保留
    assert [u.name for u in stored.plan.unplaced] == ["外滩源"]
    # 两个必去各有归宿（已排 / unplaced）——不应触发任何补披露
    assert not [a for a in stored.plan.assumptions if "覆盖审计自动补记" in a]


def test_unplaced_twin_names_are_not_conflated():
    # 外滩源已排；外滩是另一个景点——chip 不得被互含误清（dedupe 只认全等/
    # poi_id）。must「外滩」落在 unplaced 里 = 三分律满足，零噪音。
    app, store = _app_with(
        [_visit("v1", "外滩源")],
        must=["外滩源", "外滩"],
        unplaced=[UnplacedCandidate(name="外滩")],
    )
    with TestClient(app) as client:
        r = _get(client)
    assert r.status_code == 200
    stored = _stored(store)
    assert [u.name for u in stored.plan.unplaced] == ["外滩"]
    assert not [a for a in stored.plan.assumptions if "覆盖审计自动补记" in a]


def test_distinct_site_substitution_gets_disclosed():
    # 2026-11-17 精化：余量「源」非通用修饰——must「外滩」被排成「外滩源」
    # 不算覆盖、也不在 unplaced、无披露 → 补披露行（必去不允许被邻近景点
    # 静默顶替）。
    app, store = _app_with([_visit("v1", "外滩源")], must=["外滩源", "外滩"])
    with TestClient(app) as client:
        r = _get(client)
    assert r.status_code == 200
    stored = _stored(store)
    lines = [a for a in stored.plan.assumptions if "覆盖审计自动补记" in a]
    assert len(lines) == 1 and "外滩" in lines[0]


def test_yield_disclosure_in_session_counts():
    # 让位披露已在会话级 assumptions 里（不在 plan.assumptions）——也算已披露，
    # 不重复补行（真实案：中心大厦因离城日策略移出必去，披露在 session 侧）
    app, store = _app_with([_visit("v1", "外滩")], must=["豫园", "外滩"])
    session = store.get("s-ct", device_id="dev-1")
    session.assumptions = ["豫园因雨天规则未排入，已让位"]
    store.save(session)
    with TestClient(app) as client:
        r = _get(client)
    assert r.status_code == 200
    stored = _stored(store)
    assert not [a for a in stored.plan.assumptions if "覆盖审计自动补记" in a]


def test_english_and_city_modifier_musts_covered():
    # 英文裸名（ZHUJIAZUI 案）与城市前缀短名（中心大厦案）都算已覆盖，零噪音
    app, store = _app_with(
        [
            _visit("v1", "朱家角古镇", name_en="Zhujiajiao Ancient Town"),
            _visit("v2", "上海中心大厦", (11, 0), (12, 30)),
        ],
        must=["ZHUJIAJIAO", "中心大厦"],
    )
    with TestClient(app) as client:
        r = _get(client)
    assert r.status_code == 200
    stored = _stored(store)
    assert not [a for a in stored.plan.assumptions if "覆盖审计自动补记" in a]


def test_multiple_missing_musts_each_disclosed():
    # 上海 2 天三必去案形状：多个必去同时被丢——逐个披露，不吞不并
    app, store = _app_with(
        [_visit("v1", "外滩")],
        must=["豫园", "上海中心大厦", "外滩"],
    )
    with TestClient(app) as client:
        r = _get(client)
    assert r.status_code == 200
    stored = _stored(store)
    lines = [a for a in stored.plan.assumptions if "覆盖审计自动补记" in a]
    assert len(lines) == 2
    assert any("豫园" in x for x in lines)
    assert any("上海中心大厦" in x for x in lines)


def test_clean_plan_is_silent():
    app, store = _app_with(
        [_visit("v1", "豫园"), _visit("v2", "外滩", (11, 0), (12, 0))],
        must=["豫园", "外滩"],
    )
    with TestClient(app) as client:
        r = _get(client)
    assert r.status_code == 200
    stored = _stored(store)
    assert not [a for a in stored.plan.assumptions if "覆盖审计自动补记" in a]
    assert stored.plan.unplaced == []
