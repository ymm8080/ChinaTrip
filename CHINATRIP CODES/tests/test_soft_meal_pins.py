# -*- coding: utf-8 -*-
"""2026-11-01 晚拍板回归：午饭/顺路餐厅/晚饭不钉死（系统餐软锚）。

pinned=False + soft_pin=True 的餐件：非铁律 19（用户可拖/可改时/LLM 可
挪），solver 仍锚定落位（普通日零漂移；弹性日午餐 ±30+可缩 30、晚餐
±30 滑窗）；挪日修复不把餐件当搁浅景点。
"""

from datetime import time

from app.services.agent.plan import _reconcile_transfer_days
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import insertion_schedule_day, solve_plan


def _meal(item_id, at, *, dur=60, soft=True) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        category="food",
        city="西安",
        day=1,
        start_time=at,
        end_time=time(at.hour + 1, at.minute),
        duration_minutes=dur,
        pinned=False,
        soft_pin=soft,
    )


def _visit(item_id, *, dur=60) -> VisitItem:
    return VisitItem(
        item_id=item_id, name=item_id, city="西安", day=1, duration_minutes=dur
    )


def _mins(t: time) -> int:
    return t.hour * 60 + t.minute


def test_soft_meal_not_pinned_but_anchored_normal_day():
    """普通日（无大点）：解钉午餐仍锚在 12:00（零漂移），不自由漂移。"""
    day = DayPlan(
        day=1, base_city="西安", items=[_visit("a", dur=90), _meal("l1", time(12, 0))]
    )
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    lunch = next(
        i for i in solved.items if isinstance(i, VisitItem) and i.item_id == "l1"
    )
    assert lunch.pinned is False and lunch.soft_pin is True
    assert lunch.start_time == time(12, 0)


def test_soft_meal_free_without_start_time_not_anchored():
    """无时刻的系统餐件不构成锚（排序自由），但也不该崩。"""
    m = VisitItem(
        item_id="m1",
        name="m1",
        category="food",
        city="西安",
        day=1,
        duration_minutes=60,
        pinned=False,
        soft_pin=True,
    )
    day = DayPlan(day=1, base_city="西安", items=[_visit("a", dur=90), m])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    got = next(
        i for i in solved.items if isinstance(i, VisitItem) and i.item_id == "m1"
    )
    assert got.start_time is not None


def test_soft_lunch_flex_day_slides_and_shortens():
    """弹性日（240 分钟大点）：解钉午餐与钉住午餐同权（±30/可缩 30）。"""
    big = _visit("big", dur=240)
    lunch = _meal("l1", time(12, 0))
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["西安"],
        days=[DayPlan(day=1, base_city="西安", items=[big, lunch])],
    )
    solved = solve_plan(plan, poi_hours=[], meal_flex=True)
    assert solved is not None
    items = [i for i in solved.days[0].items if isinstance(i, VisitItem)]
    big2 = next(i for i in items if i.item_id == "big")
    l2 = next(i for i in items if i.item_id == "l1")
    assert big2.start_time is not None and l2.start_time is not None
    assert 11 * 60 + 30 <= _mins(l2.start_time) <= 12 * 60 + 30
    # 不重叠
    assert l2.end_time <= big2.start_time or l2.start_time >= big2.end_time


def test_soft_dinner_anchored_normal_day_and_flex_window():
    """普通日：解钉晚餐锚在落位（18:00）；弹性日：±30 滑窗、时长不变。"""
    dinner = _meal("d1", time(18, 0))

    def _plan(d: VisitItem) -> ItineraryPlan:
        return ItineraryPlan(
            itinerary_id="it1",
            cities=["西安"],
            days=[DayPlan(day=1, base_city="西安", items=[_visit("big", dur=240), d])],
        )

    normal = solve_plan(_plan(_meal("d1", time(18, 0))), poi_hours=[])
    assert normal is not None
    d_n = next(
        i
        for i in normal.days[0].items
        if isinstance(i, VisitItem) and i.item_id == "d1"
    )
    assert d_n.start_time == time(18, 0)

    flex = solve_plan(_plan(dinner), poi_hours=[], meal_flex=True)
    assert flex is not None
    d_f = next(
        i for i in flex.days[0].items if isinstance(i, VisitItem) and i.item_id == "d1"
    )
    assert d_f.start_time is not None
    assert 17 * 60 + 30 <= _mins(d_f.start_time) <= 18 * 60 + 30
    assert _mins(d_f.end_time) - _mins(d_f.start_time) == 60  # 晚餐不缩时长


def test_reconcile_does_not_strand_soft_meal_on_departure_day():
    """离城日早晨航班：解钉晚餐不再被当搁浅景点挪前一天/丢弃。"""
    dinner = _meal("d1", time(18, 0))
    dinner.day = 2
    flight = TransferItem(
        day=2,
        seq=1,
        mode="flight",
        item_id="t1",
        from_city="西安",
        to_city="上海",
        start_time=time(9, 0),
        end_time=time(12, 0),
        duration_minutes=180,
    )
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["西安", "上海"],
        days=[
            DayPlan(day=1, base_city="西安", items=[]),
            DayPlan(day=2, base_city="西安", items=[flight, dinner]),
        ],
    )
    _reconcile_transfer_days(plan)
    d2 = next(
        i for i in plan.days[1].items if isinstance(i, VisitItem) and i.item_id == "d1"
    )
    assert d2.day == 2 and d2.start_time == time(18, 0)
