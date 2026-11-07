# -*- coding: utf-8 -*-
"""2026-11-03 拍板「重要景点不要放在到达和离开的那天，那两天适合轻松的
CityWalk（回民街式街区）或 SHOW」回归：

1. 选层认领分区：tier≤4 重磅让开转场日（有整天优先），tier8 街区
   反向优先转场日（2026-11-03 名录序后街区=8）。
2. 主环同口径：未被预占的重磅落上转场日时让位（PRIORITY_EARLY=off
   路径）。
3. 软偏好不拦可行性：全程皆转场日（短程多城）重磅照排。
4. 评分器 edge_day_heavy 软罚与选层同向（LNS 跨天重排不把重磅挪回
   边日）；街区/演出/pinned/tier=None 豁免。
"""

from __future__ import annotations

from app.services.agent.plan import PlanningAgent
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.scoring import plan_score

_LOC = (104.06, 30.66)


def _cand(name: str, *, tags=None, source=None, loc=_LOC):
    c: dict = {"name": name, "city": "成都", "category": "sight", "location": loc}
    if tags is not None:
        c["tags"] = tags
    if source is not None:
        c["source"] = source
    return c


def _days_by_name(items: list[dict]) -> dict[str, int]:
    return {it["name"]: it["day"] for it in items}


# --- ① 选层认领分区 --------------------------------------------------------


def test_heavy_avoids_transfer_day_street_takes_it():
    cands = [
        _cand("世遗点", tags=["unesco"]),
        _cand("街区点", tags=["街区"]),
        _cand("普通点"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"成都": (1, 3)}, transfer_days={2}
    )
    days = _days_by_name(items)
    # 重磅落无转场腿的整天；街区（回民街式 CityWalk）接手转场日
    assert days["世遗点"] == 1
    assert days["街区点"] == 2
    assert days["普通点"] == 1


def test_all_transfer_days_still_schedules():
    """短程多城全程皆转场日：分区无整天可让（软偏好），排得上优先。"""
    cands = [_cand("世遗点", tags=["unesco"]), _cand("普通点")]
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, transfer_days={1, 2}
    )
    assert {it["name"] for it in items} == {"世遗点", "普通点"}


# --- ② 主环让位（PRIORITY_EARLY=off 无预占路径） ---------------------------


def test_main_loop_demotes_heavy_from_transfer_day(monkeypatch):
    monkeypatch.setenv("CHINATRIP_PRIORITY_EARLY", "off")
    # 坐标错开 >1.5km（同点互认并卡会把普通点一并拽去 day2，验不出
    # 让位本身；族卡已废，贴邻同日圈 5km 软偏好同向不破断言）。
    cands = [
        _cand("世遗点", tags=["unesco"], loc=(104.06, 30.66)),
        _cand("普通点", loc=(104.08, 30.66)),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, transfer_days={1}
    )
    days = _days_by_name(items)
    assert days["世遗点"] == 2  # 重磅让开 day1 转场日
    # 2026-11-07 并卡拍板：独立点各自成簇，簇分日梯子按 (tier,pos)
    # 排——两簇都避开转场日 day1 顺延 day2（主环无腾空日回填机制，
    # 同坐标共享簇=族件跟锚同日的旧形态已废）。
    assert days["普通点"] == 2


# --- ③ 评分器 --------------------------------------------------------------


def _visit(item_id, *, tier=None, pinned=False, category="sight", day=1, **kw):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city="成都",
        day=day,
        duration_minutes=60,
        tier=tier,
        pinned=pinned,
        category=category,
        **kw,
    )


def _leg(day=1):
    return TransferItem(
        item_id="t1",
        day=day,
        seq=1,
        mode="train",
        from_city="成都",
        to_city="重庆",
    )


def _plan(days: list[DayPlan]) -> ItineraryPlan:
    return ItineraryPlan(itinerary_id="it1", cities=["成都", "重庆"], days=days)


def test_scorer_penalizes_heavy_on_transfer_day():
    heavy = _visit("v1", tier=2)
    day = DayPlan(day=1, base_city="成都", items=[heavy, _leg()])
    sc = plan_score(_plan([day]))
    assert sc.soft["edge_day_heavy"] == -12
    assert sc.counts["edge_day_heavy"] == 1


def test_scorer_heavy_on_full_day_zero():
    heavy = _visit("v1", tier=1, day=2)
    d1 = DayPlan(day=1, base_city="成都", items=[_leg()])
    d2 = DayPlan(day=2, base_city="重庆", items=[heavy])
    sc = plan_score(_plan([d1, d2]))
    assert sc.soft["edge_day_heavy"] == 0


def test_scorer_counts_each_heavy():
    a, b = _visit("v1", tier=1), _visit("v2", tier=4)
    day = DayPlan(day=1, base_city="成都", items=[a, b, _leg()])
    sc = plan_score(_plan([day]))
    assert sc.soft["edge_day_heavy"] == -24


def test_scorer_street_and_none_tier_exempt():
    street = _visit("v1", tier=8)
    unknown = _visit("v2")
    day = DayPlan(day=1, base_city="成都", items=[street, unknown, _leg()])
    sc = plan_score(_plan([day]))
    assert sc.soft["edge_day_heavy"] == 0  # 街区正是边日想要的东西


def test_scorer_pinned_and_show_exempt():
    pinned = _visit("v1", tier=1, pinned=True)
    show = _visit("v2", tier=3, category="entertainment", best_visit_time="show")
    day = DayPlan(day=1, base_city="成都", items=[pinned, show, _leg()])
    sc = plan_score(_plan([day]))
    assert sc.soft["edge_day_heavy"] == 0  # 铁律 19 + 拍板明说边日适合 SHOW
