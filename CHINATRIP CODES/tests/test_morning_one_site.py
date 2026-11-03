# -*- coding: utf-8 -*-
"""上午一个点（2026-11-03 用户拍板「上午一般只排一个点」）。

口径：12 点前开场的观光点（非餐/非酒店）每天 ≤1——排程软偏好
（双 morning 窗点/用户多钉无他档仍可双晨，罚不拦可行性）、CP 路
同罚、兜底游标跳 12 点、评分器计 morning_crowd 软罚。与
「上午不许空」（morning_fill/blank_morning）合成双向口径。
"""

from datetime import time

from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.scoring import plan_score
from app.services.itinerary.solver import insertion_schedule_day, solve_day

_NOON = 12 * 60


def _visit(item_id, *, dur=90, day=1, **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city="西安",
        day=day,
        duration_minutes=dur,
        **kw,
    )


def _lunch(day=1) -> VisitItem:
    return VisitItem(
        item_id=f"lunch-{day}",
        name="午饭",
        category="food",
        city="西安",
        day=day,
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        pinned=True,
    )


def _mins(t: time) -> int:
    return t.hour * 60 + t.minute


def _morning_visits(solved) -> list[VisitItem]:
    vis = [
        i
        for i in solved.items
        if isinstance(i, VisitItem) and (i.category or "") not in ("food", "hotel")
    ]
    return [i for i in vis if _mins(i.start_time) < _NOON]


def test_insertion_second_site_moves_after_lunch():
    a = _visit("a", dur=90)
    b = _visit("b", dur=90)
    day = DayPlan(day=1, base_city="西安", items=[a, b, _lunch()])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    morning = _morning_visits(solved)
    assert len(morning) == 1
    bb = next(i for i in solved.items if i.item_id == "b")
    assert _mins(bb.start_time) >= _NOON  # 上午罚把 b 顶到午后


def test_insertion_matrix_polish_keeps_one_morning_site():
    items = [_visit("a", dur=60), _visit("b", dur=60), _visit("c", dur=60)]
    day = DayPlan(day=1, base_city="西安", items=items)
    matrix = {(x, y): 30 for x in "abc" for y in "abc" if x != y}
    solved = insertion_schedule_day(day, poi_hours=[], travel_minutes=matrix)
    assert solved is not None
    vis = [i for i in solved.items if isinstance(i, VisitItem)]
    assert all(i.start_time is not None for i in vis)
    assert len(_morning_visits(solved)) == 1  # 打磨不得靠双晨点省走行


def test_dual_morning_window_items_still_placed():
    # 软罚不拦可行性：两个 morning 窗点无他档 → 照排双晨
    m1 = _visit("m1", dur=60, best_visit_time="morning")
    m2 = _visit("m2", dur=60, best_visit_time="morning")
    day = DayPlan(day=1, base_city="西安", items=[m1, m2])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    vis = [i for i in solved.items if isinstance(i, VisitItem)]
    assert all(i.start_time is not None for i in vis)
    assert len(_morning_visits(solved)) == 2


def test_pinned_morning_pair_untouched():
    # 铁律 19：用户多钉照排，罚只引导后续自由点，不动钉
    a = _visit("a", dur=60, start_time=time(9, 0), pinned=True)
    b = _visit("b", dur=60, start_time=time(10, 30), pinned=True)
    day = DayPlan(day=1, base_city="西安", items=[a, b])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    aa = next(i for i in solved.items if i.item_id == "a")
    bb = next(i for i in solved.items if i.item_id == "b")
    assert aa.start_time == time(9, 0)
    assert bb.start_time == time(10, 30)


def test_cp_day_one_morning_site():
    a = _visit("a", dur=90)
    b = _visit("b", dur=90)
    day = DayPlan(day=1, base_city="西安", items=[a, b])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    assert len(_morning_visits(solved)) == 1


def test_cp_day_travel_matrix_one_morning_site():
    a = _visit("a", dur=90)
    b = _visit("b", dur=90)
    day = DayPlan(day=1, base_city="西安", items=[a, b])
    matrix = {("a", "b"): 30, ("b", "a"): 30}
    solved = solve_day(day, poi_hours=[], travel_minutes=matrix)
    assert solved is not None
    # travel 目标只比走行无最早偏好：0 晨也合规（≤1 上界口径）；上午
    # 不空的下界由选点层/morning_fill 保障。
    assert len(_morning_visits(solved)) <= 1


def test_fallback_cursor_jumps_to_noon():
    from app.services.agent.plan import _fallback_sequence_times

    a = _visit("a", dur=90)
    b = _visit("b", dur=90)
    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["西安"],
        days=[DayPlan(day=1, base_city="西安", items=[a, b])],
    )
    _fallback_sequence_times(plan)
    assert a.start_time == time(9, 0)
    assert b.start_time is not None and _mins(b.start_time) >= _NOON


def test_plan_score_counts_morning_crowd():
    a = _visit("a", dur=60, start_time=time(9, 0), end_time=time(10, 0))
    b = _visit("b", dur=60, start_time=time(10, 30), end_time=time(11, 30))
    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["西安"],
        days=[DayPlan(day=1, base_city="西安", items=[a, b])],
    )
    sc = plan_score(plan)
    assert sc.counts["morning_crowd"] == 1
    assert sc.soft["morning_crowd"] == -12
    # 单晨点/无晨点不罚
    b2 = _visit("b", dur=60, start_time=time(13, 0), end_time=time(14, 0))
    plan2 = ItineraryPlan(
        itinerary_id="t2",
        cities=["西安"],
        days=[DayPlan(day=1, base_city="西安", items=[a.model_copy(deep=True), b2])],
    )
    assert plan_score(plan2).counts["morning_crowd"] == 0
