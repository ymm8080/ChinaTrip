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
    _morning_window,
    _night_window,
    attach_hotel_mornings,
    attach_hotel_nights,
    attach_hotel_stays,
    is_hotel_checkin,
    is_hotel_morning,
    is_hotel_night,
    reanchor_hotel_mornings,
    sync_hotel_pair,
)
from app.services.agent.plan import (
    _fallback_sequence_times,
    _plan_lunch_slot,
    _retime_meal_placeholders,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
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


# ------------------------------------------------------------- 餐占位终装避让


def _meal_placeholder(item_id: str, start: time, duration: int) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        category="food",
        city="测试城",
        day=1,
        start_time=start,
        end_time=time(start.hour, start.minute + duration)
        if start.minute + duration < 60
        else time(
            start.hour + (start.minute + duration) // 60, (start.minute + duration) % 60
        ),
        duration_minutes=duration,
        soft_pin=True,
    )


def test_final_lunch_placeholder_retimes_after_structural_move():
    lunch = _meal_placeholder("food-lunch-ph-d1", time(12, 0), 90)
    visit = VisitItem(
        item_id="moved-visit",
        name="后移参访",
        city="测试城",
        day=1,
        start_time=time(11, 0),
        end_time=time(12, 30),
        duration_minutes=90,
    )
    day = DayPlan(day=1, base_city="测试城", items=[lunch, visit])
    _retime_meal_placeholders(_plan([day]))
    assert (lunch.start_time, lunch.end_time) == (time(12, 30), time(14, 0))


def test_final_dinner_placeholder_moves_or_drops_without_overlap():
    dinner = _meal_placeholder("food-dinner-ph-d1", time(18, 30), 60)
    show = VisitItem(
        item_id="moved-show",
        name="后移演出",
        category="entertainment",
        city="测试城",
        day=1,
        start_time=time(17, 30),
        end_time=time(18, 50),
        duration_minutes=80,
    )
    day = DayPlan(day=1, base_city="测试城", items=[dinner, show])
    _retime_meal_placeholders(_plan([day]))
    assert (dinner.start_time, dinner.end_time) == (time(18, 50), time(19, 50))

    blocked = _meal_placeholder("food-dinner-ph-d1", time(17, 30), 60)
    day = DayPlan(day=1, base_city="测试城", items=[blocked, show])
    _retime_meal_placeholders(_plan([day]))
    assert blocked not in day.items


def test_final_placeholder_never_moves_real_meal():
    lunch = _meal_placeholder("food-lunch-ph-d1", time(12, 0), 90)
    real = _meal_placeholder("real-food", time(11, 39), 60)
    day = DayPlan(day=1, base_city="测试城", items=[lunch, real])
    _retime_meal_placeholders(_plan([day]))
    assert real.start_time == time(11, 39)
    assert lunch not in day.items


def test_final_real_food_absorbs_lunch_placeholder():
    """2026-11-13 用户拍板「餐厅应该插入午餐卡」：真餐卡占午餐窗 → 占位
    撤除、真餐卡即餐卡，不再 11:30 空白午饭+12:00 餐厅并排两张餐卡。"""
    lunch = _meal_placeholder("food-lunch-ph-d1", time(11, 30), 90)
    real = _meal_placeholder("real-food", time(12, 0), 90)
    day = DayPlan(day=1, base_city="测试城", items=[lunch, real])
    _retime_meal_placeholders(_plan([day]))
    assert lunch not in day.items
    assert (real.start_time, real.end_time) == (time(12, 0), time(13, 30))


def test_final_dinner_real_food_keeps_lunch_placeholder():
    """反向锚：真晚餐卡不顶午餐占位——各餐窗占位只被同窗真餐吸收。"""
    lunch = _meal_placeholder("food-lunch-ph-d1", time(11, 30), 90)
    dinner_real = _meal_placeholder("real-food", time(17, 30), 90)
    day = DayPlan(day=1, base_city="测试城", items=[lunch, dinner_real])
    _retime_meal_placeholders(_plan([day]))
    assert lunch in day.items
    assert (lunch.start_time, lunch.end_time) == (time(11, 30), time(13, 0))
    assert (dinner_real.start_time, dinner_real.end_time) == (time(17, 30), time(19, 0))


# ------------------------------------------- 每晚酒店卡（2026-11-07 用户指令）


def _night_days():
    """两天行程：day1 有带时刻观光 + 晚餐占位；day2 傍晚航班回家。"""
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _flight(start=(9, 0), end=(11, 30)),
            VisitItem(
                item_id="w1",
                name="回民街",
                city="西安",
                day=1,
                start_time=time(14, 0),
                end_time=time(16, 0),
                duration_minutes=120,
            ),
            VisitItem(
                item_id="food-dinner-ph-d1",
                name="晚饭（自由安排）",
                category="food",
                city="西安",
                day=1,
                start_time=time(18, 0),
                end_time=time(19, 30),
                duration_minutes=90,
                soft_pin=True,
            ),
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _flight(2, start=(18, 0), end=(20, 30), frm="西安", to="上海"),
        ],
    )
    return [d1, d2]


def test_attach_night_appends_at_day_end():
    days = _night_days()
    notes = attach_hotel_nights(days)
    assert notes, "假设区必须亮出每晚酒店卡注记"
    cards = [i for i in days[0].items if is_hotel_night(i)]
    assert len(cards) == 1
    card = cards[0]
    assert days[0].items[-1] is card  # 末位（晚餐占位之后）
    assert card.category == "hotel" and card.soft_pin and not card.pinned
    # 窗口=末件（晚餐 19:30 收尾）+30 起、60 分钟
    assert (card.start_time, card.end_time) == (time(20, 0), time(21, 0))
    assert card.city == "西安"  # 末个观光件之城


def test_attach_night_uses_latest_end_not_list_order():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit(
                "dinner",
                dur=120,
                cat="food",
                start_time=time(17, 30),
                end_time=time(19, 30),
                soft_pin=True,
            ),
            _visit(
                "show",
                dur=80,
                cat="entertainment",
                start_time=time(17, 30),
                end_time=time(18, 50),
            ),
        ],
    )
    attach_hotel_nights([day])
    card = next(i for i in day.items if is_hotel_night(i))
    assert (card.start_time, card.end_time) == (time(20, 0), time(21, 0))


def test_attach_night_skips_outbound_transfer_day():
    """末件=离程航班（到达城不再是更晚日子的宿城）：当晚到家，不插。"""
    days = _night_days()
    attach_hotel_nights(days)
    assert not any(is_hotel_night(i) for i in days[1].items)  # day2 傍晚回沪


def test_attach_night_arrival_transfer_stays_in_destination():
    """夕发朝至落在宿城：夜卡城=到达城，窗口贴到达时刻。"""
    d1 = DayPlan(
        day=1,
        base_city="上海",
        items=[
            _flight(1, start=(19, 0), end=(22, 0), frm="上海", to="西安"),
        ],
    )
    d2 = DayPlan(day=2, base_city="西安", items=[])
    attach_hotel_nights([d1, d2])
    cards = [i for i in d1.items if is_hotel_night(i)]
    assert len(cards) == 1
    assert cards[0].city == "西安"
    assert cards[0].start_time == time(22, 30)  # 到达 22:00 + 30


def test_attach_night_idempotent_and_empty_day_default():
    days = _night_days()
    assert attach_hotel_nights(days)[0] is not None
    again = attach_hotel_nights(days)
    assert again == []  # 已有夜卡的天不重复插
    assert len([i for i in days[0].items if is_hotel_night(i)]) == 1
    empty = DayPlan(day=3, base_city="成都", items=[])
    attach_hotel_nights([empty])
    cards = [i for i in empty.items if is_hotel_night(i)]
    assert len(cards) == 1
    assert (cards[0].start_time, cards[0].end_time) == (time(21, 0), time(22, 0))
    assert cards[0].city == "成都"  # 空天回落醒来城


def test_night_window_clamps():

    assert _night_window(None) == (21 * 60, 22 * 60)
    assert _night_window(22 * 60 + 30) == (23 * 60, 24 * 60 - 1)  # 贴 23:00，封顶 23:59
    assert _night_window(23 * 60 + 50) == (23 * 60 + 50, 23 * 60 + 59)  # 贴末件不回拨


def test_night_card_last_visit_city_wins():
    """当天活动城（末个观光件）优先于醒来城——晚间换城日夜宿新城。"""
    d1 = DayPlan(
        day=1,
        base_city="上海",
        items=[
            VisitItem(
                item_id="w1",
                name="外滩",
                city="上海",
                day=1,
                start_time=time(10, 0),
                end_time=time(12, 0),
                duration_minutes=120,
            ),
            VisitItem(
                item_id="w2",
                name="西湖",
                city="杭州",
                day=1,
                start_time=time(15, 0),
                end_time=time(18, 0),
                duration_minutes=180,
            ),
        ],
    )
    d2 = DayPlan(day=2, base_city="杭州", items=[])
    attach_hotel_nights([d1, d2])
    card = next(i for i in d1.items if is_hotel_night(i))
    assert card.city == "杭州"
    assert (card.start_time, card.end_time) == (time(18, 30), time(19, 30))


# ------------------------------ 到达后每天出发点是 HOTEL（2026-11-13 拍板）


def _morning_days():
    """沪→西安 3 天：d1 落地、d2 正常日、d3 傍晚回家。"""
    d1 = DayPlan(
        day=1,
        base_city="上海",
        items=[
            _flight(),
            _visit(
                "w1",
                city="西安",
                start_time=time(14, 0),
                end_time=time(16, 0),
            ),
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit(
                "w2",
                day=2,
                start_time=time(9, 0),
                end_time=time(11, 0),
            ),
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_flight(3, start=(18, 0), end=(20, 30), frm="西安", to="上海")],
    )
    return [d1, d2, d3]


def test_morning_window():
    assert _morning_window(None) == (8 * 60 + 30, 9 * 60)  # 空天：日始前离店
    assert _morning_window(540) == (480, 510)  # 首件 09:00 → 08:00-08:30
    assert _morning_window(390) == (330, 360)  # 首件 06:30 → 05:30-06:00
    assert _morning_window(30) is None  # 首件 00:30 放不下
    # 首件是跨城交通：按铁律 4 的 90 分钟衔接缓冲预留
    assert _morning_window(1080, transfer=True) == (960, 990)  # 18:00 → 16:00-16:30


def test_attach_mornings_after_each_hotel_night():
    days = _morning_days()
    attach_hotel_stays(days)
    attach_hotel_nights(days)
    notes = attach_hotel_mornings(days)
    assert notes and "从酒店出发" in notes[0]
    # 落地日不插（当天另有入住卡）
    assert not any(is_hotel_morning(i) for i in days[0].items)
    d2 = next(i for i in days[1].items if is_hotel_morning(i))
    assert d2.item_id == "hotel-morning-d2"
    assert (d2.start_time, d2.end_time) == (time(8, 0), time(8, 30))
    assert d2.city == "西安" and d2.soft_pin and not d2.pinned
    assert days[1].items[0] is d2  # 当天第一张卡
    # 回家日（d3 无夜卡）仍从前一晚酒店退房出发：18:00 航班按铁律 4
    # 90 分钟衔接缓冲 → 16:00-16:30 离店
    d3 = next(i for i in days[2].items if is_hotel_morning(i))
    assert (d3.start_time, d3.end_time) == (time(16, 0), time(16, 30))


def test_attach_morning_empty_day_before_day_start():
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit("w1", start_time=time(14, 0), end_time=time(16, 0)),
        ],
    )
    d2 = DayPlan(day=2, base_city="西安", items=[])
    attach_hotel_nights([d1, d2])
    attach_hotel_mornings([d1, d2])
    card = next(i for i in d2.items if is_hotel_morning(i))
    assert (card.start_time, card.end_time) == (time(8, 30), time(9, 0))


def test_attach_morning_requires_previous_night_card():
    """前一晚没住酒店（无夜卡：夜车/删卡）→ 次日不插晨卡。"""
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit("w1", start_time=time(14, 0), end_time=time(16, 0)),
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("w2", day=2, start_time=time(9, 0), end_time=time(11, 0)),
        ],
    )
    assert attach_hotel_mornings([d1, d2]) == []
    assert not any(is_hotel_morning(i) for i in d2.items)


def test_attach_morning_inherits_verified_hotel_and_is_idempotent():
    days = _morning_days()
    attach_hotel_nights(days)
    night = next(i for i in days[0].items if is_hotel_night(i))
    night.name = "丽枫酒店钟楼店"
    night.poi_id = "B0H"
    night.address = "碑林区南大街1号"
    night.location = GeoPoint(lon=108.95, lat=34.26)
    assert attach_hotel_mornings(days)
    card = next(i for i in days[1].items if is_hotel_morning(i))
    assert card.name == "🏨 从酒店出发（丽枫酒店钟楼店）"
    assert card.poi_id == "B0H"
    assert card.address == "碑林区南大街1号"
    assert card.location == night.location
    assert attach_hotel_mornings(days) == []  # 已有晨卡不重复插


def test_sync_hotel_pair_both_directions():
    d1 = DayPlan(day=1, base_city="西安", items=[])
    d2 = DayPlan(day=2, base_city="西安", items=[])
    attach_hotel_nights([d1, d2])
    attach_hotel_mornings([d1, d2])
    night = next(i for i in d1.items if is_hotel_night(i))
    morning = next(i for i in d2.items if is_hotel_morning(i))
    night.name = "酒店甲"
    night.poi_id = "B1"
    night.address = "甲路1号"
    night.location = GeoPoint(lon=108.9, lat=34.2)
    sync_hotel_pair([d1, d2], night, hotel_name="酒店甲")
    assert morning.name == "🏨 从酒店出发（酒店甲）"
    assert morning.poi_id == "B1"
    assert morning.address == "甲路1号"
    assert morning.location == night.location
    # 反向：晨卡写入新酒店 → 前一晚夜卡同步（夜卡名=纯店名）
    morning.poi_id = "B2"
    morning.address = "乙路2号"
    morning.location = GeoPoint(lon=108.8, lat=34.1)
    sync_hotel_pair([d1, d2], morning, hotel_name="酒店乙")
    assert night.name == "酒店乙"
    assert night.poi_id == "B2"
    assert night.address == "乙路2号"
    assert morning.name == "🏨 从酒店出发（酒店乙）"


def test_reanchor_morning_pulls_back_for_far_hotel_only_earlier():
    card = VisitItem(
        item_id="hotel-morning-d2",
        name="🏨 从酒店出发",
        category="hotel",
        city="西安",
        day=2,
        start_time=time(8, 0),
        end_time=time(8, 30),
        duration_minutes=30,
        soft_pin=True,
        location=GeoPoint(lon=120.0, lat=30.0),
    )
    visit = VisitItem(
        item_id="w2",
        name="西湖",
        city="西安",
        day=2,
        start_time=time(9, 0),
        end_time=time(11, 0),
        duration_minutes=120,
        location=GeoPoint(lon=120.0, lat=30.18),  # ≈20km → 打车 75 分钟
    )
    day = DayPlan(day=2, base_city="西安", items=[card, visit])
    reanchor_hotel_mornings([day])
    assert (card.start_time, card.end_time) == (time(7, 15), time(7, 45))
    # 只回拨不后移：已更早的卡不动（用户手拖）
    card.start_time, card.end_time = time(6, 30), time(7, 0)
    reanchor_hotel_mornings([day])
    assert (card.start_time, card.end_time) == (time(6, 30), time(7, 0))
    # keep_ids：本回合被用户改的卡完全不动
    card.start_time, card.end_time = time(8, 0), time(8, 30)
    reanchor_hotel_mornings([day], keep_ids={"hotel-morning-d2"})
    assert (card.start_time, card.end_time) == (time(8, 0), time(8, 30))


def test_dedupe_keeps_night_and_morning_cards():
    """同名同 poi 的一段住宿两端不得被跨天孪生合并并掉一张。"""
    from app.services.agent.plan import dedupe_plan_visits

    night = VisitItem(
        item_id="hotel-night-d1",
        name="丽枫酒店",
        poi_id="B1",
        category="hotel",
        city="西安",
        day=1,
        start_time=time(20, 0),
        end_time=time(21, 0),
        duration_minutes=60,
        soft_pin=True,
    )
    morning = VisitItem(
        item_id="hotel-morning-d2",
        name="🏨 从酒店出发（丽枫酒店）",
        poi_id="B1",
        category="hotel",
        city="西安",
        day=2,
        start_time=time(8, 0),
        end_time=time(8, 30),
        duration_minutes=30,
        soft_pin=True,
    )
    plan = _plan(
        [
            DayPlan(day=1, base_city="西安", items=[night]),
            DayPlan(day=2, base_city="西安", items=[morning]),
        ]
    )
    assert dedupe_plan_visits(plan) == []
    assert night in plan.days[0].items
    assert morning in plan.days[1].items
