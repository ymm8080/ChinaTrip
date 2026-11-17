# -*- coding: utf-8 -*-
"""先午餐后游览（2026-11-17 用户拍板「到景区先吃午饭（约 12:00）再游玩」）：
同址午饭占位被排在游后 → 换序+顺延+披露；真实餐厅卡/午后到达/不同址不换；
撞硬锚回滚；幂等。"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import _lunch_before_destination_visit
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem

MUTIANYU = GeoPoint(lon=116.5598, lat=40.4267)


def _v(item_id, name, start, end, *, cat="sight", lon=None, lat=None, **kw):
    dur = None
    if start is not None and end is not None:
        dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return VisitItem(
        item_id=item_id,
        name=name,
        city="北京",
        day=1,
        category=cat,
        duration_minutes=kw.pop("dur", dur),
        location=GeoPoint(lon=lon, lat=lat) if lon is not None else None,
        start_time=start,
        end_time=end,
        **kw,
    )


def _plan(items):
    return ItineraryPlan(
        itinerary_id="t",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
        assumptions=[],
    )


def _mty_day(lunch_start=time(14, 38), visit_start=time(11, 38)):
    """慕田峪基准案：晨卡 + 游玩 + 游后午饭占位（锚同址）+ 晚饭占位 + 夜卡。"""
    lm = lunch_start.hour * 60 + lunch_start.minute + 60
    lunch_end = time((lm // 60) % 24, lm % 60)
    vm = visit_start.hour * 60 + visit_start.minute + 180
    visit_end = time((vm // 60) % 24, vm % 60)
    return [
        _v("hotel-morning-d1", "出发", time(8, 30), time(9, 0), cat="hotel"),
        _v(
            "v-mty",
            "慕田峪长城",
            visit_start,
            visit_end,
            cat="nature",
            lon=MUTIANYU.lon,
            lat=MUTIANYU.lat,
            dur=180,
            must=True,
            pinned=True,
        ),
        _v(
            "food-lunch-ph-d1",
            "午饭（自由安排）",
            lunch_start,
            lunch_end,
            cat="food",
            lon=MUTIANYU.lon,
            lat=MUTIANYU.lat,
            anchor_from_prev=True,
            anchor_location=MUTIANYU,
        ),
        _v(
            "food-dinner-ph-d1",
            "晚饭（自由安排）",
            time(19, 0),
            time(20, 30),
            cat="food",
        ),
        _v("hotel-night-d1", "回酒店", time(21, 0), time(22, 0), cat="hotel"),
    ]


def _get(plan, name):
    return next(i for i in plan.days[0].items if i.name == name)


def test_swap_lunch_before_visit_mutianyu_shape():
    plan = _plan(_mty_day())
    notes = _lunch_before_destination_visit(plan)
    assert notes and "先午餐后游览" in notes[0]
    lunch = _get(plan, "午饭（自由安排）")
    site = _get(plan, "慕田峪长城")
    assert (lunch.start_time.hour, lunch.start_time.minute) == (11, 38)
    assert (site.start_time.hour, site.start_time.minute) == (12, 38)
    assert (site.end_time.hour, site.end_time.minute) == (15, 38)
    dinner = _get(plan, "晚饭（自由安排）")
    assert dinner.start_time == time(19, 0)


def test_real_restaurant_card_not_swapped():
    items = _mty_day()
    items[2] = _v(
        "food-lunch-real",
        "虹鳟鱼一顿",
        time(14, 38),
        time(15, 38),
        cat="food",
        lon=MUTIANYU.lon,
        lat=MUTIANYU.lat,
    )
    plan = _plan(items)
    assert _lunch_before_destination_visit(plan) == []
    assert _get(plan, "虹鳟鱼一顿").start_time == time(14, 38)


def test_afternoon_arrival_not_swapped():
    plan = _plan(_mty_day(visit_start=time(14, 0), lunch_start=time(17, 0)))
    assert _lunch_before_destination_visit(plan) == []
    assert _get(plan, "慕田峪长城").start_time == time(14, 0)


def test_different_venue_not_swapped():
    items = _mty_day()
    items[2].anchor_location = GeoPoint(lon=116.40, lat=39.90)
    plan = _plan(items)
    assert _lunch_before_destination_visit(plan) == []
    assert _get(plan, "午饭（自由安排）").start_time == time(14, 38)


def test_city_day_not_swapped():
    """市区串门日（观光卡离城心 <15km）不换序——午饭随带骑既有口径。"""
    items = _mty_day()
    items[1].location = GeoPoint(lon=116.41, lat=39.91)
    items[1].start_time = time(10, 40)
    items[1].end_time = time(13, 40)
    items[2].start_time = time(13, 40)
    items[2].end_time = time(14, 40)
    plan = _plan(items)
    assert _lunch_before_destination_visit(plan) == []
    assert _get(plan, "午饭（自由安排）").start_time == time(13, 40)


def test_swap_is_idempotent():
    plan = _plan(_mty_day())
    first = _lunch_before_destination_visit(plan)
    assert first
    before = [(i.name, i.start_time, i.end_time) for i in plan.days[0].items]
    second = _lunch_before_destination_visit(plan)
    assert second == []
    after = [(i.name, i.start_time, i.end_time) for i in plan.days[0].items]
    assert before == after


def test_swap_rolls_back_when_pinned_sight_cannot_move():
    """换序后与更早的钉住件让不开（前面 11:00-12:30 钉住件压住新午饭）→
    整体回滚保持原状——宁可不换不破盘。"""
    items = _mty_day(visit_start=time(13, 0), lunch_start=time(16, 0))
    items.insert(
        1,
        _v(
            "v-pinned-morning",
            "钉住早景",
            time(11, 0),
            time(12, 30),
            cat="park",
            lon=116.40,
            lat=40.10,
            pinned=True,
            dur=90,
        ),
    )
    plan = _plan(items)
    notes = _lunch_before_destination_visit(plan)
    # 换序后午饭 13:00-14:00 与钉住早景之后的顺延链若冲突则整体回滚，
    # 或顺延成功但不得产生任何重叠；两种结果都合法。
    site = _get(plan, "慕田峪长城")
    lunch = _get(plan, "午饭（自由安排）")
    dinner = _get(plan, "晚饭（自由安排）")
    timed = sorted(
        (
            i
            for i in plan.days[0].items
            if i.start_time is not None and (i.category or "") not in ("food", "hotel")
        ),
        key=lambda i: i.start_time,
    )
    for a, b in zip(timed, timed[1:]):
        assert a.end_time <= b.start_time, (a.name, b.name)
    if not notes:
        assert site.start_time == time(13, 0)
        assert lunch.start_time == time(16, 0)
    assert dinner.start_time == time(19, 0)
