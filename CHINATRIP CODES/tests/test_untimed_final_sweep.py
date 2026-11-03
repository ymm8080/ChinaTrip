# -*- coding: utf-8 -*-
"""无时刻参访卡终闸回归（2026-11-03 用户 Day4 事故：「太平森林公园」
None-None 垫在 19:30《梦回大唐》之后交付，腿标注再画一条 64.2km/949
分钟的演出→公园腿，「FIX PERMANENT FOR ALL SITES」）。

根因三层与本测对应：
①build 终局清算嵌在「转场日清算有产出」条件下——普通日（非转场）
  None-None 卡原样交付 → _finalize_untimed_visits 无条件重解→移除留痕；
②读路径（GET/save）只愈腿间隔不愈无时刻卡——旧会话永久回放
  → drop_untimed_visits 读闸（钉/餐/酒店不动）；
③leg_pairs 链不区分已排/未排——已排演出→未排公园画出巨腿
  → 未排卡断链。
"""

from datetime import time as _t

from app.services.agent.plan import PlanningAgent, drop_dangling_visits
from app.services.itinerary.legs import annotate_legs, leg_pairs
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

# 真实库位（session 4b309e Day4 载荷坐标）
XYT = GeoPoint(lon=108.9420, lat=34.2393)  # 小雁塔
XABW = GeoPoint(lon=108.9416, lat=34.2385)  # 西安博物院
SZRB = GeoPoint(lon=108.9466, lat=34.1961)  # 陕西自然博物馆
MHDAT = GeoPoint(lon=108.9400, lat=34.3411)  # 《梦回大唐》
TPGY = GeoPoint(lon=108.6530, lat=33.9102)  # 太平森林公园（鄠邑区 64km 外）


def _incident_day4() -> DayPlan:
    """事故形态复刻：三白点+19:30 演出已排，远郊 180 分钟公园 None-None 垫底。"""
    items = [
        VisitItem(
            item_id="v12",
            name="小雁塔",
            city="西安",
            day=4,
            category="attraction",
            duration_minutes=120,
            start_time=_t(9, 0),
            end_time=_t(11, 0),
            location=XYT,
        ),
        VisitItem(
            item_id="food-lunch-d4",
            name="午饭（自由安排）",
            city="西安",
            day=4,
            category="food",
            duration_minutes=30,
            start_time=_t(11, 30),
            end_time=_t(12, 0),
            soft_pin=True,
        ),
        VisitItem(
            item_id="v13",
            name="西安博物院",
            city="西安",
            day=4,
            category="museum",
            duration_minutes=120,
            start_time=_t(12, 0),
            end_time=_t(14, 0),
            location=XABW,
        ),
        VisitItem(
            item_id="v15",
            name="陕西自然博物馆",
            city="西安",
            day=4,
            category="museum",
            duration_minutes=120,
            start_time=_t(14, 41),
            end_time=_t(16, 41),
            location=SZRB,
        ),
        VisitItem(
            item_id="v19",
            name="《梦回大唐》",
            city="西安",
            day=4,
            category="entertainment",
            best_visit_time="show",
            duration_minutes=80,
            start_time=_t(19, 30),
            end_time=_t(20, 50),
            location=MHDAT,
        ),
        VisitItem(
            item_id="v7",
            name="太平森林公园",
            city="西安",
            day=4,
            category="nature",
            duration_minutes=180,
            location=TPGY,
        ),
    ]
    return DayPlan(day=4, base_city="西安", items=items)


def _plan() -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-untimed",
        cities=["西安"],
        days=[_incident_day4()],
        assumptions=[],
    )


def _bare_agent(solve_result=None) -> PlanningAgent:
    """跳过 __init__ 的裸 agent：_finalize_untimed_visits 只用 self._solve。"""
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = lambda plan, meal_flex=True, **kw: solve_result  # type: ignore[method-assign]
    return agent


# --- ① build 终闸：普通日 None-None 卡不再交付 ------------------------------


def test_finalize_drops_untimed_park_after_evening_show():
    plan = _plan()
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    names = [i.name for i in out.days[0].items]
    assert "太平森林公园" not in names, "远郊公园装不下必须移除留痕，不得垫在演出后交付"
    assert "《梦回大唐》" in names and "小雁塔" in names
    assert any("太平森林公园" in str(a) for a in out.assumptions), "移除必须留痕"


def test_finalize_noop_when_all_timed():
    plan = _plan()
    park = next(i for i in plan.days[0].items if i.item_id == "v7")
    plan.days[0].items.remove(park)
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    assert out.assumptions == []


def test_finalize_respects_resolved_plan():
    """CP 重解成功且排上全部时刻→沿用重解结果（不清算）。"""
    plan = _plan()
    solved = _plan()
    park = next(i for i in solved.days[0].items if i.item_id == "v7")
    park.start_time = _t(9, 0)
    park.end_time = _t(12, 0)
    out = _bare_agent(solve_result=solved)._finalize_untimed_visits(plan)
    assert any(i.item_id == "v7" for i in out.days[0].items)
    assert out.assumptions == []


# --- ② 读闸：旧会话打开即清 ----------------------------------------------


def test_read_gate_drops_untimed_keeps_pinned_and_food():
    plan = _plan()
    day = plan.days[0]
    show = next(i for i in day.items if i.item_id == "v19")
    show.pinned = True
    show.start_time = None  # 钉住但未排（铁律 19 面儿）
    notes = drop_dangling_visits(plan)
    names = [i.name for i in day.items]
    assert "太平森林公园" not in names
    assert "《梦回大唐》" in names, "钉点不删"
    assert "午饭（自由安排）" in names, "餐不删"
    assert notes and any("太平森林公园" in str(n) for n in notes)
    assert not any("《梦回大唐》" in str(n) for n in notes)


def test_read_gate_noop_on_clean_plan():
    plan = _plan()
    plan.days[0].items = [i for i in plan.days[0].items if i.item_id != "v7"]
    assert drop_dangling_visits(plan) == []


def test_read_gate_keeps_fully_untimed_day():
    """整日全未排的降级日/骨架日不清——读闸不能把骨架会话读穿成空壳
    （test_plan_dedupe_gate 夹具即全未排形态）。"""
    plan = _plan()
    for i in plan.days[0].items:
        if isinstance(i, VisitItem):
            i.start_time = None
            i.end_time = None
    assert drop_dangling_visits(plan) == []
    names = [i.name for i in plan.days[0].items]
    assert "太平森林公园" in names and "《梦回大唐》" in names


# --- ③ 腿标注：未排卡断链，不再画巨腿 --------------------------------------


def test_leg_pairs_break_chain_at_untimed():
    plan = _plan()
    pairs = leg_pairs(plan)
    legs_from_show = [a.name for a, _b, _km in pairs if a.item_id == "v19"]
    assert legs_from_show == [], "演出后垫的未排公园不得成为腿终点"


def test_annotate_legs_no_bogus_leg_into_untimed():
    plan = _plan()
    annotate_legs(plan)
    show = next(i for i in plan.days[0].items if i.item_id == "v19")
    assert show.distance_to_next_km is None
    assert show.next_walk_minutes is None
    museum = next(i for i in plan.days[0].items if i.item_id == "v13")
    assert museum.distance_to_next_km is not None, "已排链上腿照画"
