# -*- coding: utf-8 -*-
"""落地首停·酒店入住回归（2026-11-01 用户拍板「行程里应该有 HOTEL」）。

口径：火车/飞机落地过夜城 → 插「🏨 酒店入住」卡（落地+90 到店、
休整 60 分钟），当天首个观光 ≥ 落地+150（2.5h）；末段回家/汽车/
深夜放不下不插；删卡后首停地板仍在（CP+插入+兜底三路同口径）；
入住卡软锚；午餐槽贴卡尾或让位、绝不切分入住卡。
"""

from datetime import time

from app.services.agent.hotel_stays import (
    _card_window,
    attach_hotel_stays,
    is_hotel_checkin,
)
from app.services.agent.plan import _fallback_sequence_times, _plan_lunch_slot
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import solve_plan


def _flight(
    day=1,
    *,
    start=(9, 0),
    end=(11, 30),
    frm="上海",
    to="西安",
    mode="flight",
    seq=1,
):
    return TransferItem(
        item_id=f"t{day}-{seq}",
        day=day,
        seq=seq,
        from_city=frm,
        to_city=to,
        mode=mode,
        start_time=time(*start),
        end_time=time(*end),
        duration_minutes=(end[0] * 60 + end[1]) - (start[0] * 60 + start[1]),
    )


def _visit(item_id, *, dur=90, day=1, city="西安", cat=None, **kw):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city=city,
        day=day,
        duration_minutes=dur,
        category=cat,
        **kw,
    )


def _card(day=1, city="西安", land_end=(11, 30)):
    s = land_end[0] * 60 + land_end[1] + 90
    return VisitItem(
        item_id=f"hotel-checkin-d{day}",
        name="🏨 酒店入住（放行李·休整）",
        category="hotel",
        city=city,
        day=day,
        start_time=time(s // 60, s % 60),
        end_time=time((s + 60) // 60, (s + 60) % 60),
        duration_minutes=60,
        pinned=False,
        soft_pin=True,
    )


def _plan(days, cities=("上海", "西安")):
    return ItineraryPlan(itinerary_id="it1", cities=list(cities), days=days)


def _stay_days():
    d1 = DayPlan(day=1, base_city="上海", items=[_flight(), _visit("w1")])
    d2 = DayPlan(day=2, base_city="西安", items=[_visit("w2", day=2)])
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_flight(3, start=(15, 0), end=(17, 30), frm="西安", to="上海")],
    )
    return [d1, d2, d3]


# ------------------------------------------------------------------ attach


def test_attach_inserts_checkin_after_landing():
    days = _stay_days()
    notes = attach_hotel_stays(days)
    cards = [i for i in days[0].items if is_hotel_checkin(i)]
    assert len(cards) == 1
    card = cards[0]
    assert (card.start_time, card.end_time) == (time(13, 0), time(14, 0))
    assert card.category == "hotel" and card.city == "西安"
    assert card.pinned is False and card.soft_pin is True
    assert card.duration_minutes == 60
    assert days[0].items.index(card) == days[0].items.index(days[0].items[0]) + 1
    assert not any(is_hotel_checkin(i) for i in days[2].items)  # 末段回家不插
    assert notes and "酒店" in notes[0]


def test_card_window_clamps_late_landings():
    assert _card_window(690) == (780, 840)  # 11:30 落地 → 13:00-14:00
    assert _card_window(1320) == (1320, 1380)  # 22:00 落地 → 贴落地 60 分钟
    assert _card_window(1400) == (1400, 1439)  # 23:20 落地 → 压缩到日终
    assert _card_window(1420) is None  # 23:40 落地放不下


def test_attach_idempotent():
    days = _stay_days()
    attach_hotel_stays(days)
    attach_hotel_stays(days)
    assert len([i for d in days for i in d.items if is_hotel_checkin(i)]) == 1


def test_mid_city_stay_gets_card():
    d1 = DayPlan(day=1, base_city="上海", items=[_flight()])
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[_flight(2, start=(10, 0), end=(12, 0), frm="西安", to="重庆")],
    )
    d3 = DayPlan(day=3, base_city="重庆", items=[_visit("w3", day=3, city="重庆")])
    d4 = DayPlan(
        day=4,
        base_city="重庆",
        items=[_flight(4, start=(15, 0), end=(17, 30), frm="重庆", to="上海")],
    )
    days = [d1, d2, d3, d4]
    attach_hotel_stays(days)
    assert len([i for i in days[0].items if is_hotel_checkin(i)]) == 1
    ck = [i for i in days[1].items if is_hotel_checkin(i)]
    assert len(ck) == 1 and ck[0].city == "重庆"
    assert (ck[0].start_time, ck[0].end_time) == (time(13, 30), time(14, 30))
    assert not any(is_hotel_checkin(i) for i in days[3].items)


def test_car_transfer_gets_no_card():
    d1 = DayPlan(
        day=1,
        base_city="上海",
        items=[_flight(mode="car"), _visit("w1")],
    )
    d2 = DayPlan(day=2, base_city="西安", items=[])
    attach_hotel_stays([d1, d2])
    assert not any(is_hotel_checkin(i) for i in d1.items)


# ----------------------------------------------------------------- solver


def test_insertion_first_visit_floor_with_card():
    day = DayPlan(day=1, base_city="上海", items=[_flight(), _card(), _visit("w1")])
    solved = solve_plan(_plan([day]), poi_hours=[])
    assert solved is not None
    v = next(i for i in solved.days[0].items if i.item_id == "w1")
    assert v.start_time == time(14, 0)  # 落地+150（卡 13:00-14:00 之后）
    c = next(i for i in solved.days[0].items if is_hotel_checkin(i))
    assert (c.start_time, c.end_time) == (time(13, 0), time(14, 0))


def test_insertion_first_visit_floor_without_card():
    day = DayPlan(day=1, base_city="上海", items=[_flight(), _visit("w1")])
    solved = solve_plan(_plan([day]), poi_hours=[])
    assert solved is not None
    v = next(i for i in solved.days[0].items if i.item_id == "w1")
    assert v.start_time == time(14, 0)  # 无卡：首停地板=落地+2.5h
    assert v.start_time != time(13, 0)  # 不再是旧口径 te+90


def test_cp_first_visit_floor_without_card():
    day = DayPlan(day=1, base_city="上海", items=[_flight(), _visit("w1")])
    solved = solve_plan(_plan([day]), poi_hours=[], scheduler="cp")
    assert solved is not None
    v = next(i for i in solved.days[0].items if i.item_id == "w1")
    assert v.start_time == time(14, 0)


def test_food_keeps_90_buffer_after_landing():
    day = DayPlan(
        day=1,
        base_city="上海",
        items=[_flight(), _visit("d1", dur=60, cat="food")],
    )
    solved = solve_plan(_plan([day]), poi_hours=[])
    assert solved is not None
    v = next(i for i in solved.days[0].items if i.item_id == "d1")
    assert v.start_time == time(13, 0)  # 餐饮豁免 2.5h 地板，铁律 4 照旧


# ---------------------------------------------------------------- fallback


def test_fallback_floor_with_and_without_card():
    with_card = DayPlan(
        day=1, base_city="上海", items=[_flight(), _card(), _visit("w1")]
    )
    without = DayPlan(day=2, base_city="上海", items=[_flight(2), _visit("w2", day=2)])
    plan = _plan([with_card, without])
    _fallback_sequence_times(plan)
    v1 = next(i for i in with_card.items if i.item_id == "w1")
    v2 = next(i for i in without.items if i.item_id == "w2")
    assert v1.start_time == time(14, 0)
    assert v2.start_time == time(14, 0)


# ------------------------------------------------------------- 午餐槽避让


def test_lunch_slot_hugs_card_tail():
    day = DayPlan(
        day=1,
        base_city="上海",
        items=[_flight(start=(8, 0), end=(9, 30)), _visit("w1", city="西安")],
    )
    attach_hotel_stays([day, DayPlan(day=2, base_city="西安", items=[])])
    card = next(i for i in day.items if is_hotel_checkin(i))
    assert (card.start_time, card.end_time) == (time(11, 0), time(12, 0))
    slot = _plan_lunch_slot(day)
    assert slot is not None and slot[0][0] == time(12, 0)  # 贴卡尾开饭


def test_lunch_slot_none_when_card_eats_window():
    day = DayPlan(
        day=1,
        base_city="上海",
        items=[_flight(start=(9, 30), end=(11, 0)), _visit("w1", city="西安")],
    )
    attach_hotel_stays([day, DayPlan(day=2, base_city="西安", items=[])])
    card = next(i for i in day.items if is_hotel_checkin(i))
    assert card.start_time == time(12, 30)  # 卡吃掉午餐窗
    assert _plan_lunch_slot(day) is None  # 过点到店不插午餐，也不切卡
