# -*- coding: utf-8 -*-
"""PR2 插入式排时主路回归（2026-11-01《求解器升级建议》落地）。

锚点优先+最廉插入+重定位打磨；solve_plan 默认走插入主路，
CHINATRIP_SCHEDULER=cp 回旧 CP 主路（A/B 基准对照）。
"""

from datetime import time

from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    PoiHours,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import insertion_schedule_day, solve_plan

_ALL_DAY = PoiHours(poi_id="p_all", opens=time(8, 0), closes=time(21, 0))


def _visit(item_id, *, dur=60, day=1, city="西安", **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city=city,
        day=day,
        duration_minutes=dur,
        **kw,
    )


def _lunch(day=1, *, soft=True, at=time(12, 0)) -> VisitItem:
    return VisitItem(
        item_id=f"lunch-{day}",
        name="午饭（自由安排）",
        category="food",
        city="西安",
        day=day,
        start_time=at,
        end_time=time(at.hour + 1, at.minute),
        duration_minutes=60,
        pinned=True,
        soft_pin=soft,
    )


def _mins(t: time) -> int:
    return t.hour * 60 + t.minute


def _plan(days):
    return ItineraryPlan(itinerary_id="it1", cities=["西安"], days=days)


def test_insertion_basic_places_all_in_order():
    items = [_visit("a", dur=90), _visit("b", dur=60), _visit("c", dur=120)]
    day = DayPlan(day=1, base_city="西安", items=items)
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    vis = [i for i in solved.items if isinstance(i, VisitItem)]
    assert all(i.start_time is not None for i in vis)
    starts = [_mins(i.start_time) for i in vis]
    assert starts == sorted(starts)
    for prev, nxt in zip(vis, vis[1:]):
        assert prev.end_time <= nxt.start_time


def test_insertion_session_show_lands_on_session():
    s = _visit(
        "show",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="多场（约15:00/20:00）",
    )
    day = DayPlan(day=1, base_city="西安", items=[s, _lunch()])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    show = next(i for i in solved.items if i.item_id == "show")
    assert show.start_time in (time(15, 0), time(20, 0))


def test_insertion_respects_transfer_buffer():
    flight = TransferItem(
        day=1,
        seq=1,
        mode="flight",
        item_id="t1",
        from_city="西安",
        to_city="上海",
        start_time=time(17, 0),
        end_time=time(20, 0),
        duration_minutes=180,
    )
    v = _visit("big", dur=180)
    day = DayPlan(day=1, base_city="西安", items=[flight, v, _lunch()])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    big = next(i for i in solved.items if i.item_id == "big")
    # 17:00-90 缓冲=15:30 前必须结束
    assert _mins(big.end_time) <= 15 * 60 + 30


def test_insertion_180_big_morning_abuts_lunch():
    v = _visit("big", dur=180)
    day = DayPlan(day=1, base_city="西安", items=[v, _lunch()])
    solved = insertion_schedule_day(day, poi_hours=[], meal_flex=True)
    assert solved is not None
    big = next(i for i in solved.items if i.item_id == "big")
    lunch = next(i for i in solved.items if i.item_id == "lunch-1")
    assert big.start_time == time(9, 0)  # 无 matrix 背靠背合法：紧贴午餐
    assert lunch.start_time == time(12, 0)


def test_insertion_240_big_after_shortened_lunch():
    v = _visit("big", dur=240)
    day = DayPlan(day=1, base_city="西安", items=[v, _lunch()])
    solved = insertion_schedule_day(day, poi_hours=[], meal_flex=True)
    assert solved is not None
    big = next(i for i in solved.items if i.item_id == "big")
    lunch = next(i for i in solved.items if i.item_id == "lunch-1")
    # ±30+缩30：上午容量 12:30（=210 分钟）装不下 240——贴缩短午餐后
    assert _mins(big.start_time) >= 12 * 60
    assert _mins(lunch.start_time) >= 11 * 60  # 允许提前
    assert lunch.end_time <= big.start_time  # 无重叠
    lunch_span = _mins(lunch.end_time) - _mins(lunch.start_time)
    assert lunch_span >= 30  # 缩短下限 30 分钟


def test_insertion_entry_cap_16_for_regular_sights():
    v = _visit("late", dur=90)
    dinner = VisitItem(
        item_id="din",
        name="晚餐",
        category="food",
        city="西安",
        day=1,
        start_time=time(19, 0),
        end_time=time(20, 0),
        duration_minutes=60,
        pinned=True,
    )
    day = DayPlan(day=1, base_city="西安", items=[v, dinner])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    late = next(i for i in solved.items if i.item_id == "late")
    assert _mins(late.start_time) <= 16 * 60


def test_insertion_none_when_evening_show_blocked_by_flight():
    s = _visit(
        "show",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="傍晚/晚间场（约17:30/19:30两场）",
    )
    flight = TransferItem(
        day=1,
        seq=1,
        mode="flight",
        item_id="t1",
        from_city="西安",
        to_city="上海",
        start_time=time(17, 0),
        end_time=time(20, 0),
        duration_minutes=180,
    )
    day = DayPlan(day=1, base_city="西安", items=[s, flight, _lunch()])
    assert insertion_schedule_day(day, poi_hours=[]) is None


def test_solve_plan_insertion_default_and_cp_flag(monkeypatch):
    items = [_visit("a", dur=90), _lunch(), _visit("b", dur=120)]
    plan = _plan([DayPlan(day=1, base_city="西安", items=items)])

    solved = solve_plan(plan, poi_hours=[])
    assert solved is not None
    assert all(
        i.start_time is not None
        for i in solved.days[0].items
        if isinstance(i, VisitItem)
    )

    monkeypatch.setenv("CHINATRIP_SCHEDULER", "cp")
    plan2 = _plan(
        [
            DayPlan(
                day=1,
                base_city="西安",
                items=[_visit("a", dur=90), _lunch(), _visit("b", dur=120)],
            )
        ]
    )
    solved2 = solve_plan(plan2, poi_hours=[])
    assert solved2 is not None
    assert all(
        i.start_time is not None
        for i in solved2.days[0].items
        if isinstance(i, VisitItem)
    )


def test_insertion_travel_matrix_gaps_enforced():
    a = _visit("a", dur=60)
    b = _visit("b", dur=60, opening_hours=None)
    day = DayPlan(day=1, base_city="西安", items=[a, b])
    matrix = {("a", "b"): 50, ("b", "a"): 50}
    solved = insertion_schedule_day(day, poi_hours=[], travel_minutes=matrix)
    assert solved is not None
    vis = [i for i in solved.items if isinstance(i, VisitItem)]
    vis.sort(key=lambda i: i.start_time)
    for prev, nxt in zip(vis, vis[1:]):
        gap = _mins(nxt.start_time) - _mins(prev.end_time)
        assert gap >= 50  # matrix 相邻走行间隔硬闸


def test_insertion_pinned_item_is_anchor():
    pinned = VisitItem(
        item_id="pin",
        name="钉点",
        city="西安",
        day=1,
        start_time=time(10, 0),
        end_time=time(11, 0),
        duration_minutes=60,
        pinned=True,
    )
    v = _visit("big", dur=180)
    day = DayPlan(day=1, base_city="西安", items=[pinned, v, _lunch()])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    pin2 = next(i for i in solved.items if i.item_id == "pin")
    assert pin2.start_time == time(10, 0)  # 用户钉纹丝不动
    big = next(i for i in solved.items if i.item_id == "big")
    # 09:00-12:00 会被钉点(±30 块)与午餐夹住 → 落下午
    assert _mins(big.start_time) >= 13 * 60
