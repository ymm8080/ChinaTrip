# -*- coding: utf-8 -*-
"""腿间隔三层修复回归（2026-11-03 用户 Day2 事故：大明宫 13:30+90min→
西安城墙 15:00 背靠背零车程，「路上时间没有计算，全站点永久修」）。

根因三层与本测对应：
①旧 session 载荷（11-02 _leg_windows 改造前兜底产物）永不自愈
   → heal_leg_gaps 读闸修复（GET/save 挂点在 API 层）；
②CP 路 separate 不可行时 _attempt(False) 把零间隔合法化
   → solver 改弃日（见 test_solver.test_infeasible_travel_separation_
   drops_day），本文件补 solve_plan 链路视角；
③校验对 end==start 贴脸不报
   → rules.travel_gap_violations 铁律 7 绊网（餐/钉/无坐标豁免）。
"""

from datetime import time as _t

from app.services.agent.plan import heal_leg_gaps
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    VisitItem,
)
from app.services.itinerary.rules import haversine_km, taxi_leg_min, validate_plan
from app.services.itinerary.solver import solve_plan

# 真实库位（session 5cbf9073 Day2 载荷坐标）
SLB = GeoPoint(lon=108.9551, lat=34.2242)  # 陕西历史博物馆
DMG = GeoPoint(lon=108.9639, lat=34.3121)  # 大明宫国家考古遗址公园
XQ = GeoPoint(lon=108.9471, lat=34.2757)  # 西安城墙
WYG = GeoPoint(lon=108.9012, lat=34.2953)  # 汉长安城未央宫


def _stale_day2() -> DayPlan:
    """事故形态复刻：午餐 12:00-13:30 后三点背靠背 13:30/15:00/16:30。"""
    items = [
        VisitItem(
            item_id="v1",
            name="陕西历史博物馆",
            city="西安",
            day=2,
            category="museum",
            duration_minutes=120,
            start_time=_t(9, 0),
            end_time=_t(11, 0),
            location=SLB,
        ),
        VisitItem(
            item_id="food-lunch-d2",
            name="午饭（自由安排）",
            city="西安",
            day=2,
            category="food",
            duration_minutes=90,
            start_time=_t(12, 0),
            end_time=_t(13, 30),
            soft_pin=True,
        ),
        VisitItem(
            item_id="v2",
            name="大明宫国家考古遗址公园",
            city="西安",
            day=2,
            category="attraction",
            duration_minutes=90,
            start_time=_t(13, 30),
            end_time=_t(15, 0),
            location=DMG,
        ),
        VisitItem(
            item_id="v3",
            name="西安城墙",
            city="西安",
            day=2,
            category="attraction",
            # 75 分钟轻点：11-04 大点闸 15:30 后，90 分钟大点在 15:40 挪后
            # 落位越闸——自愈机制测试改用轻点保持原语义。
            duration_minutes=75,
            start_time=_t(15, 0),
            end_time=_t(16, 30),
            location=XQ,
        ),
        VisitItem(
            item_id="v4",
            name="汉长安城未央宫",
            city="西安",
            day=2,
            category="attraction",
            duration_minutes=90,
            start_time=_t(16, 30),
            end_time=_t(18, 0),
            location=WYG,
        ),
    ]
    return DayPlan(day=2, base_city="西安", items=items)


def _sight_pairs(day: DayPlan) -> list[tuple[VisitItem, VisitItem]]:
    timed = sorted(
        (v for v in day.items if isinstance(v, VisitItem) and v.start_time),
        key=lambda v: v.start_time,
    )
    return [
        (a, b)
        for a, b in zip(timed, timed[1:])
        if (a.category or "") not in ("food", "hotel")
        and (b.category or "") not in ("food", "hotel")
        and a.location is not None
        and b.location is not None
    ]


# --- ① heal_leg_gaps：旧载荷读闸自愈 ---------------------------------------


def test_heal_repairs_stale_zero_gap_chain():
    day = _stale_day2()
    plan = ItineraryPlan(
        itinerary_id="it-heal", cities=["西安"], days=[day], assumptions=[]
    )
    notes = heal_leg_gaps(plan)
    assert notes, "事故载荷应触发自愈"
    v1 = next(v for v in day.items if v.item_id == "v1")
    lunch = next(v for v in day.items if v.category == "food")
    assert (v1.start_time, v1.end_time) == (_t(9, 0), _t(11, 0)), "违规点之前的好排不动"
    assert lunch.start_time == _t(12, 0), "餐（贴点拍板语义）不动"
    for a, b in _sight_pairs(day):
        if a.start_time is None or b.start_time is None:
            continue
        gap = (
            b.start_time.hour * 60
            + b.start_time.minute
            - a.end_time.hour * 60
            - a.end_time.minute
        )
        need = max(30, taxi_leg_min(haversine_km(a.location, b.location)))
        assert gap >= need, f"{a.name}→{b.name} 自愈后仍背靠背：gap={gap} need={need}"


def test_heal_noop_on_healthy_plan():
    day = _stale_day2()
    for v in day.items:
        v.start_time = None
        v.end_time = None
    plan = ItineraryPlan(
        itinerary_id="it-ok", cities=["西安"], days=[day], assumptions=[]
    )
    from app.services.agent.plan import _fallback_sequence_times

    _fallback_sequence_times(plan)  # 当前树产物带腿
    assert heal_leg_gaps(plan) == [], "健康行程零修复"


def test_heal_skips_pinned_later_item():
    """违规对晚点是用户钉——不硬修，交校验披露（铁律 19 面）。"""
    day = _stale_day2()
    wall = next(v for v in day.items if v.item_id == "v3")
    wall.pinned = True
    plan = ItineraryPlan(
        itinerary_id="it-pin", cities=["西安"], days=[day], assumptions=[]
    )
    assert heal_leg_gaps(plan) == []
    assert wall.start_time == _t(15, 0), "钉点不动"


# --- ② solve_plan 链路：紧日子弃日不再产出背靠背 ---------------------------


def test_solve_plan_tight_day_degrades_not_packs():
    """腿矩阵把当天挤爆时，CP 弃日→失败日保留输入（未排交兜底披露），
    绝不返回 gap=0 的整日方案。"""
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            VisitItem(
                item_id="m",
                name="早馆",
                city="北京",
                day=1,
                category="museum",
                duration_minutes=180,
                best_visit_time="morning",
            ),
            VisitItem(
                item_id="e",
                name="午馆",
                city="北京",
                day=1,
                category="museum",
                duration_minutes=180,
                best_visit_time="afternoon",
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-tight", cities=["北京"], days=[day], assumptions=[]
    )
    matrix = {("m", "e"): 240, ("e", "m"): 240}
    solved = solve_plan(
        plan,
        poi_hours=[PoiHours(poi_id="__none__", opens=_t(9, 0), closes=_t(21, 0))],
        travel_minutes=matrix,
    )
    d = next(x for x in solved.days if x.day == 1)
    placed = sorted(
        (v for v in d.items if v.start_time and v.end_time),
        key=lambda v: v.start_time,
    )
    for a, b in zip(placed, placed[1:]):
        gap = (
            b.start_time.hour * 60
            + b.start_time.minute
            - a.end_time.hour * 60
            - a.end_time.minute
        )
        need = max(30, matrix.get((a.item_id, b.item_id), 30))
        assert gap >= need, "solve_plan 仍产出零间隔背靠背"


# --- ③ rules 绊网：铁律 7 ---------------------------------------------------


def test_validate_flags_back_to_back_zero_gap():
    plan = ItineraryPlan(
        itinerary_id="it-v",
        cities=["西安"],
        days=[_stale_day2()],
        assumptions=[],
    )
    report = validate_plan(plan, poi_hours=[])
    rule7 = [v for v in report.violations if v.rule_id == 7]
    assert rule7, "背靠背零车程必须报铁律 7"
    assert not report.ok


def test_validate_exempts_food_pinned_and_locationless_pairs():
    """餐贴点/钉点/无坐标对不报——与 heal、_leg_windows 同口径。"""
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            VisitItem(
                item_id="f",
                name="午饭",
                city="西安",
                day=1,
                category="food",
                duration_minutes=90,
                start_time=_t(12, 0),
                end_time=_t(13, 30),
                location=GeoPoint(lon=108.94, lat=34.26),
            ),
            VisitItem(
                item_id="s1",
                name="餐后点",
                city="西安",
                day=1,
                category="attraction",
                duration_minutes=90,
                start_time=_t(13, 30),
                end_time=_t(15, 0),  # 餐→点贴点合法
                location=GeoPoint(lon=108.96, lat=34.31),
            ),
            VisitItem(
                item_id="s2",
                name="钉点",
                city="西安",
                day=1,
                category="attraction",
                duration_minutes=90,
                pinned=True,
                start_time=_t(15, 0),
                end_time=_t(16, 30),
                location=GeoPoint(lon=109.21, lat=34.36),
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-x", cities=["西安"], days=[day], assumptions=[]
    )
    report = validate_plan(plan, poi_hours=[])
    assert not [v for v in report.violations if v.rule_id == 7]


# --- ④ API 读闸：GET 打开旧会话即自愈并持久化 -------------------------------


def test_get_endpoint_heals_stale_session():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.plan import get_plan_sessions, get_planning_agent, router
    from app.services.agent.plan import PlanningAgent, PlanSession, PlanSessionStore

    class _StubAdapter:
        name = "stub"

        async def chat(self, messages, *, temperature=0.3, max_tokens=None):
            raise AssertionError("GET 读闸不应调 LLM")

    agent = PlanningAgent(_StubAdapter())

    async def _noop_refresh_legs(session):
        return None

    agent.refresh_legs = _noop_refresh_legs
    app = FastAPI()
    store = PlanSessionStore()
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: store
    app.include_router(router)
    client = TestClient(app)

    session = PlanSession(session_id="s-heal", device_id="dev-1", state="ready")
    session.plan = ItineraryPlan(
        itinerary_id="it-heal-api",
        cities=["西安"],
        days=[_stale_day2()],
        assumptions=[],
    )
    store.save(session)

    resp = client.get("/api/v1/plan/s-heal", headers={"X-Device-ID": "dev-1"})
    assert resp.status_code == 200
    day = next(d for d in resp.json()["plan"]["days"] if d["day"] == 2)
    placed = sorted(
        (i for i in day["items"] if i.get("start_time")),
        key=lambda i: i["start_time"],
    )
    for a, b in zip(placed, placed[1:]):
        if a.get("category") == "food" or b.get("category") == "food":
            continue
        gap = (
            int(b["start_time"][:2]) * 60
            + int(b["start_time"][3:5])
            - int(a["end_time"][:2]) * 60
            - int(a["end_time"][3:5])
        )
        assert gap >= 30, f"GET 返回仍背靠背：{a['name']}→{b['name']} gap={gap}"
    stored = store.get("s-heal", device_id="dev-1")
    wall = next(i for i in stored.plan.days[0].items if i.item_id == "v3")
    assert wall.start_time != _t(15, 0) or wall.end_time != _t(16, 30), (
        "修复须 store.save 持久化（下次打开不再触发）"
    )
