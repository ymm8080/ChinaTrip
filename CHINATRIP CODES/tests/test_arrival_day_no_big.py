# -*- coding: utf-8 -*-
"""2026-11-05 拍板「到达第一天不适合放大块头景点，只适合小景点或
CityWalk」回归：

1. 选层预占位分区：大块头候选（>80min 非街区）认领天序把到达日压
   到队尾（有非到达日优先）；小景点照常落到达日。
2. 主环同口径（PRIORITY_EARLY=off）：未预占的大块头落上到达日让位。
3. 软偏好不拦可行性：两天窗全是到达日照排。
4. 返程末日不在到达日集：大块头可落返程日（到达专属，非转场日
   全域闸——边日轻重规则 24 已管转场全域的重磅档）。
5. 再平衡不把大块头塞进到达日：回填排序压后 + 超载分流目标过滤。
6. 评分器 arrival_day_big 软罚同向：到达侧腿（后跟内容）天的大点
   计罚；返程压轴腿不算；pinned/tier8 街区豁免。
"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import PlanningAgent
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.scoring import plan_score

_LOC = (104.06, 30.66)


def _cand(name: str, *, minutes=None, tags=None, loc=_LOC, rating=None):
    c: dict = {"name": name, "city": "成都", "category": "sight", "location": loc}
    if minutes is not None:
        c["suggested_duration_min"] = minutes
    if tags is not None:
        c["tags"] = tags
    if rating is not None:
        c["rating"] = rating
        c["rating_count"] = 100
    return c


def _spec(name: str, day: int, minutes: int) -> dict:
    return {
        "name": name,
        "city": "成都",
        "category": "sight",
        "day": day,
        "duration_minutes": minutes,
        "location": {"lon": _LOC[0], "lat": _LOC[1]},
    }


def _days_by_name(items: list[dict]) -> dict[str, int]:
    return {it["name"]: it["day"] for it in items}


# --- ① 选层预占位分区 -------------------------------------------------------


def test_big_avoids_arrival_day_small_takes_it():
    cands = [
        _cand("大块头", minutes=120),
        _cand("轻点", minutes=60),
        _cand("街区点", minutes=60, tags=["街区"]),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"成都": (1, 3)}, transfer_days={1}, arrival_days={1}
    )
    days = _days_by_name(items)
    # 大块头让开到达日；轻点/街区（CityWalk）落到达日
    assert days["大块头"] == 2
    assert days["轻点"] == 1
    assert days["街区点"] == 1


def test_main_loop_demotes_big_from_arrival_day(monkeypatch):
    monkeypatch.setenv("CHINATRIP_PRIORITY_EARLY", "off")
    cands = [_cand("大块头", minutes=120), _cand("轻点", minutes=60)]
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, transfer_days={1}, arrival_days={1}
    )
    days = _days_by_name(items)
    assert days["大块头"] == 2  # 大块头让开 day1 到达日
    assert days["轻点"] == 1  # 轻点接管到达日（到达日收轻内容）


def test_all_arrival_days_still_schedules():
    """两天窗全是到达日（短程）：分区无替代天（软偏好），排得上优先。"""
    cands = [_cand("大块头", minutes=120)]
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, transfer_days={1, 2}, arrival_days={1, 2}
    )
    assert {it["name"] for it in items} == {"大块头"}


def test_return_day_accepts_big():
    """返程末日是转场日但不是到达日：大块头可落（到达专属口径）。"""
    cands = [_cand("大块头", minutes=120)]
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, transfer_days={1, 2}, arrival_days={1}
    )
    days = _days_by_name(items)
    assert days["大块头"] == 2


# --- ② 再平衡闸 -------------------------------------------------------------


def test_backfill_prefers_small_on_arrival_day():
    # 到达日预置茶位（food 不占 4 点闸与品类封顶账），窗口收成单日
    # 避免空天争抢候选；轻点先补到 270 回填线，大块头被预算闸挡住
    picked = [_spec("到达茶位", 1, 210)]
    picked[0]["category"] = "food"
    cands = [
        _cand("候选大块头", minutes=120, rating="4.7"),
        _cand("候选轻点", minutes=60, rating="4.7"),
    ]
    out, _notes = PlanningAgent._rebalance_days(
        picked,
        cands,
        3,
        {"成都": (1, 1)},
        transfer_days=set(),
        arrival_days={1},
    )
    names = {p["name"]: p["day"] for p in out}
    # 回填先收轻点（210+60=270 恰到回填线即停），大块头不进到达日
    assert "候选大块头" not in names
    assert names["候选轻点"] == 1


def test_rebalance_overflow_avoids_arrival_day():
    picked = [
        _spec("到达小点", 1, 60),
        _spec("超载大块头", 2, 90),
        _spec("超载中点", 2, 90),
        _spec("超载大点", 2, 120),
        _spec("超载小点", 2, 90),
        _spec("他日中点", 3, 90),
        _spec("他日小点", 3, 60),
    ]
    out, _notes = PlanningAgent._rebalance_days(
        picked,
        [],
        3,
        {"成都": (1, 3)},
        transfer_days={1},
        arrival_days={1},
    )
    days = _days_by_name(out)
    # day2 超载（390>360）：大块头分流有非到达日（day3）可去就不落
    # 到达日 day1——无闸时 (leg, load, t) 最小键会让它落 day1
    assert days["超载大块头"] == 3
    assert days["到达小点"] == 1


# --- ③ 评分器 ---------------------------------------------------------------


def _visit(item_id, *, tier=None, pinned=False, minutes=120, day=1, **kw):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city="成都",
        day=day,
        duration_minutes=minutes,
        tier=tier,
        pinned=pinned,
        category="sight",
        **kw,
    )


def _leg(item_id="t1", day=1):
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=1,
        mode="train",
        from_city="西安",
        to_city="成都",
    )


def _plan(days: list[DayPlan]) -> ItineraryPlan:
    return ItineraryPlan(itinerary_id="it1", cities=["西安", "成都"], days=days)


def test_scorer_penalizes_big_on_arrival_day():
    big = _visit("v1", minutes=120)
    day = DayPlan(day=1, base_city="成都", items=[_leg(), big])
    sc = plan_score(_plan([day]))
    assert sc.soft["arrival_day_big"] == -12
    assert sc.counts["arrival_day_big"] == 1


def test_scorer_return_leg_day_not_penalized():
    """返程腿压轴（腿在当天末尾）=离城日，不算到达日。"""
    big = _visit("v1", minutes=120)
    day = DayPlan(day=2, base_city="成都", items=[big, _leg()])
    sc = plan_score(_plan([day]))
    assert sc.counts["arrival_day_big"] == 0


def test_scorer_arrival_exempt_pinned_and_street():
    pinned_big = _visit("v1", pinned=True, minutes=120, start_time=time(10, 0))
    street = _visit("v2", tier=8, minutes=120)
    day = DayPlan(day=1, base_city="成都", items=[_leg(), pinned_big, street])
    sc = plan_score(_plan([day]))
    assert sc.counts["arrival_day_big"] == 0
    assert sc.soft["arrival_day_big"] == 0


# --- ④ 王牌档收口（2026-11-08 拍板「到达日只适合简单的 CITYWALK 或
# SHOW」；西安案 D1=兵马俑 90min+骊山 180min+show 太重）----------------------


def test_ace_small_minutes_avoids_arrival_day():
    """tier≤2 小块头王牌（兵马俑库时长 90min 形态）不上到达日：库时长
    短≠轻——此前 ≤120min+簇伴≥2 破例放行是 D1 堆重根因之一。"""
    cands = [
        _cand("王牌小块头", minutes=90, tags=["5a"]),
        _cand("轻点", minutes=60),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"成都": (1, 3)}, transfer_days={1}, arrival_days={1}
    )
    days = _days_by_name(items)
    assert days["王牌小块头"] == 2
    assert days["轻点"] == 1


def test_ace_family_not_atomic_on_arrival_day():
    """含 tier≤2 王牌的原子族不得整族认领到达日（到达日整族通道的二道
    闸）：族内王牌成员被 _edge_blocked 拦下，整族让位非到达日。"""
    cands = [
        _cand("族王牌", minutes=90, tags=["5a"], loc=(104.060, 30.660)),
        _cand("族小点", minutes=60, loc=(104.064, 30.660)),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"成都": (1, 3)}, transfer_days={1}, arrival_days={1}
    )
    days = _days_by_name(items)
    assert days["族王牌"] == 2
    assert days["族小点"] == 2  # 整族原子同日（组合排日不变量）


def test_single_day_window_ace_still_schedules():
    """窗口仅一天（hi==lo）：到达日排除让位兜底——无替代日照排，
    宁排勿缺（软偏好语义不变）。"""
    cands = [_cand("孤日王牌", minutes=90, tags=["5a"])]
    items = PlanningAgent._deterministic_selection(
        cands, 1, {"成都": (1, 1)}, transfer_days=set(), arrival_days={1}
    )
    days = _days_by_name(items)
    assert days["孤日王牌"] == 1
