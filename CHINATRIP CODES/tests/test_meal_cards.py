# -*- coding: utf-8 -*-
"""2026-11-13 拍板回归：餐厅必须落在午餐卡/晚餐卡，一个餐卡只留一张真餐厅。

事故形态（上海案第 1 天）：用户钉了 19:34 的福和慧（晚餐卡），旧判据按
「与 17:30-19:30 常量窗有交集」认晚餐，19:30 后开席落在窗外 → 自动补餐
在 18:30 又插老吉士酒家，两天餐卡并排交付。
"""

from datetime import time

from app.services.agent.plan import (
    _day_meal_card_taken,
    _drop_surplus_auto_meals,
    _meal_card_slot,
    _retime_meal_placeholders,
    _retime_real_food_cards,
)
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)


def _food(item_id: str, name: str, start: time | None, dur: int = 60) -> VisitItem:
    end = (
        None
        if start is None
        else time(
            (start.hour * 60 + start.minute + dur) // 60 % 24, (start.minute + dur) % 60
        )
    )
    return VisitItem(
        item_id=item_id,
        name=name,
        category="food",
        city="上海",
        day=1,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
        pinned=item_id.startswith("v"),
        soft_pin=True,
    )


def _plan(items: list[VisitItem], day: int = 1) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it1",
        cities=["上海"],
        days=[DayPlan(day=day, base_city="上海", items=list(items))],
    )


def test_meal_card_slot_maps_by_start_time():
    """真餐厅卡按开席时刻归卡；占位件不算占卡。"""
    assert _meal_card_slot(_food("v1", "午饭店", time(12, 0))) == "lunch"
    assert _meal_card_slot(_food("v2", "福和慧", time(19, 34))) == "dinner"
    assert _meal_card_slot(_food("v3", "早茶", time(8, 30))) == "breakfast"
    assert _meal_card_slot(_food("v4", "无时刻", None)) == "untimed"
    # 占位件本身就是空餐卡
    ph = VisitItem(
        item_id="food-dinner-ph-d1",
        name="晚饭（自由安排）",
        category="food",
        city="上海",
        day=1,
        start_time=time(17, 30),
        end_time=time(18, 30),
        duration_minutes=60,
    )
    assert _meal_card_slot(ph) is None
    # 非餐条目
    sight = VisitItem(
        item_id="v9",
        name="外滩",
        category="attraction",
        city="上海",
        day=1,
        start_time=time(18, 0),
        duration_minutes=60,
    )
    assert _meal_card_slot(sight) is None


def test_day_meal_card_taken_sees_late_dinner_and_untimed():
    """19:30 后开席的晚餐也算占晚餐卡（旧窗口判据漏判的分界）。"""
    day = DayPlan(
        day=1,
        base_city="上海",
        items=[_food("v34", "福和慧", time(19, 34), dur=90)],
    )
    assert _day_meal_card_taken(day, "dinner") is True
    assert _day_meal_card_taken(day, "lunch") is False
    # 无时刻真餐件：宁空不重，两张卡都算占
    untimed = DayPlan(day=1, base_city="上海", items=[_food("v35", "某餐厅", None)])
    assert _day_meal_card_taken(untimed, "lunch") is True
    assert _day_meal_card_taken(untimed, "dinner") is True


def test_surplus_auto_dinner_dropped_against_late_user_dinner():
    """上海案原形：19:34 福和慧 + 18:30 自动老吉士 → 只留福和慧并留痕。"""
    flh = _food("v34", "福和慧", time(19, 34), dur=90)
    auto = _food("food-d1-dinner-1", "老吉士酒家（天平路店）", time(18, 30))
    plan = _plan([flh, auto])
    _drop_surplus_auto_meals(plan)
    names = [i.name for i in plan.days[0].items]
    assert names == ["福和慧"]
    assert any("撤掉重复的自动补餐" in a and "老吉士" in a for a in plan.assumptions)


def test_two_system_dinners_keep_first_only():
    a = _food("food-d1-dinner-1", "甲餐厅", time(18, 0))
    b = _food("food-d1-dinner-2", "乙餐厅", time(19, 30))
    plan = _plan([a, b])
    _drop_surplus_auto_meals(plan)
    assert [i.name for i in plan.days[0].items] == ["甲餐厅"]


def test_lunch_and_dinner_cards_both_kept():
    """午卡+晚卡各一张是合法形态，绝不误撤。"""
    lunch = _food("food-d1-lunch-1", "绿波廊", time(12, 0), dur=90)
    dinner = _food("v34", "福和慧", time(19, 34), dur=90)
    plan = _plan([lunch, dinner])
    _drop_surplus_auto_meals(plan)
    assert [i.name for i in plan.days[0].items] == ["绿波廊", "福和慧"]
    assert not plan.assumptions


def test_two_user_dinners_never_dropped():
    """两张都不是系统件（用户钉的）时本闸不撤——用户权威。"""
    a = _food("v40", "甲", time(18, 0))
    b = _food("v41", "乙", time(19, 30))
    plan = _plan([a, b])
    _drop_surplus_auto_meals(plan)
    assert [i.name for i in plan.days[0].items] == ["甲", "乙"]


def test_dinner_placeholder_absorbed_by_late_dinner_card():
    """晚饭占位件不再与 19:34 的真餐厅并排（旧窗口判据吸收不到）。

    吸收了晚占位之后，同日午卡按「每天午/晚各一张」补齐。
    """
    ph = VisitItem(
        item_id="food-dinner-ph-d1",
        name="晚饭（自由安排）",
        category="food",
        city="上海",
        day=1,
        start_time=time(17, 30),
        end_time=time(18, 30),
        duration_minutes=60,
        pinned=False,
        soft_pin=True,
    )
    flh = _food("v34", "福和慧", time(19, 34), dur=90)
    plan = _plan([ph, flh])
    _retime_meal_placeholders(plan)
    names = [i.name for i in plan.days[0].items]
    assert "晚饭（自由安排）" not in names
    assert "福和慧" in names
    # 午卡空缺由「每天午/晚各一张」补齐（不吃掉真餐厅卡）
    assert "午饭（自由安排）" in names


def test_lunch_placeholder_kept_when_only_dinner_card_taken():
    """只占晚卡时午饭占位件照常保留（两个餐卡互不牵连）。"""
    ph = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        category="food",
        city="上海",
        day=1,
        start_time=time(12, 0),
        end_time=time(13, 30),
        duration_minutes=90,
        pinned=False,
        soft_pin=True,
    )
    flh = _food("v34", "福和慧", time(19, 34), dur=90)
    plan = _plan([ph, flh])
    _retime_meal_placeholders(plan)
    assert [i.name for i in plan.days[0].items] == ["午饭（自由安排）", "福和慧"]


def test_adjacent_restaurant_absorbs_same_card_placeholder():
    """相邻但不重叠也算同卡：12:00-13:30 午占位 + 13:30 餐厅 → 占位让位。

    编辑路径的旧口径只在「撞车（重叠）」时才挪占位，13:30 开席的餐厅与
    12:00-13:30 的空占位首尾相接、无重叠，交付就成了「一个餐厅邻一个餐
    卡」。餐卡对账按卡判、不按重叠判。
    """
    ph = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        category="food",
        city="上海",
        day=1,
        start_time=time(12, 0),
        end_time=time(13, 30),
        duration_minutes=90,
        pinned=False,
        soft_pin=True,
    )
    resto = _food("v50", "某餐厅", time(13, 30), dur=60)
    plan = _plan([ph, resto])
    _retime_meal_placeholders(plan, ensure_cards=False)
    assert [i.name for i in plan.days[0].items] == ["某餐厅"]


# --- 真餐卡落位闸（2026-11-13 福和慧/老吉士「未排」案）---------------------


def _resto(
    item_id: str,
    name: str,
    *,
    hours: str | None = None,
    day: int = 1,
    dur: int = 90,
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        poi_id="poi-" + item_id,
        category="food",
        city="上海",
        day=day,
        start_time=None,
        end_time=None,
        duration_minutes=dur,
        opening_hours=hours,
        pinned=True,
        soft_pin=True,
        curated=True,
    )


def _hour_card() -> VisitItem:
    return VisitItem(
        item_id="hotel-night-d1",
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="上海",
        day=1,
        start_time=time(15, 0),
        end_time=time(16, 0),
        duration_minutes=60,
        soft_pin=True,
    )


def _flight() -> TransferItem:
    return TransferItem(
        item_id="t1",
        day=1,
        seq=1,
        from_city="北京",
        to_city="上海",
        mode="flight",
        start_time=time(9, 0),
        end_time=time(12, 0),
        duration_minutes=180,
    )


def test_untimed_restaurant_lands_on_dinner_card_after_arrival():
    """落地日午窗物理不可行（12:00 才落地）：真餐卡顺到晚卡，夜卡跟着顺延。"""
    flh = _resto("v170", "福和慧", hours="11:30-14:00,17:30-22:30")
    plan = _plan([_flight(), flh, _hour_card()])
    notes = _retime_real_food_cards(plan)
    assert flh.start_time == time(17, 30)
    assert flh.end_time == time(19, 0)
    assert flh.duration_minutes == 90
    night = plan.days[0].items[-1]
    assert night.item_id == "hotel-night-d1"
    assert night.start_time == time(19, 30)
    assert any("福和慧" in n and "晚餐" in n for n in notes)


def test_untimed_restaurant_slides_to_free_card_when_lunch_blocked():
    """目标日上午被长点占死（11:30-13:00）→ 午餐卡排不进，晚卡 17:00 开席。"""
    lunch_blocker = VisitItem(
        item_id="v1",
        name="豫园",
        category="park",
        city="上海",
        day=2,
        start_time=time(11, 30),
        end_time=time(14, 0),
        duration_minutes=90,
    )
    jesse = _resto(
        "v171", "老吉士酒家（天平路店）", hours="11:00-14:30,17:00-21:30", day=2
    )
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["上海"],
        days=[DayPlan(day=2, base_city="上海", items=[lunch_blocker, jesse])],
    )
    _retime_real_food_cards(plan)
    assert jesse.start_time == time(17, 0)
    assert jesse.end_time == time(18, 30)


def test_untimed_restaurant_uses_free_card_not_taken_one():
    """晚卡已有真餐厅 → 只能落午餐卡（一个餐卡只留一张真餐厅）。"""
    dinner = _food("v200", "绿波廊", time(18, 30), dur=60)
    dinner.day = 3
    resto = _resto("v201", "南翔馒头店", hours="10:30-20:00", day=3)
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["上海"],
        days=[DayPlan(day=3, base_city="上海", items=[dinner, resto])],
    )
    _retime_real_food_cards(plan)
    assert resto.start_time == time(11, 30)
    assert _meal_card_slot(resto) == "lunch"
    assert _meal_card_slot(dinner) == "dinner"


def test_restaurant_without_free_card_stays_and_discloses():
    """当日两卡排满（整天被大点占死、营业窗只到 14:30）→ 保留卡片 + 披露。"""
    big = VisitItem(
        item_id="v300",
        name="上海迪士尼乐园",
        category="attraction",
        city="上海",
        day=4,
        start_time=time(9, 0),
        end_time=time(20, 30),
        duration_minutes=690,
    )
    resto = _resto("v301", "某本帮菜", hours="11:00-14:30", day=4)
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["上海"],
        days=[DayPlan(day=4, base_city="上海", items=[big, resto])],
    )
    notes = _retime_real_food_cards(plan)
    assert resto.start_time is None
    assert resto in plan.days[0].items  # 绝不静默删用户选中的餐厅
    assert any("餐卡已满" in n and "某本帮菜" in n for n in notes)


def test_untimed_restaurant_does_not_squeeze_against_flight_departure():
    """离城日 17:00 航班：晚卡整段撞 90 分钟衔接缓冲 → 不硬塞。"""
    depart = TransferItem(
        item_id="t2",
        day=5,
        seq=1,
        from_city="上海",
        to_city="北京",
        mode="flight",
        start_time=time(17, 0),
        end_time=time(20, 0),
        duration_minutes=180,
    )
    resto = _resto("v302", "某晚宴", hours="17:00-22:00", day=5)
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["上海"],
        days=[DayPlan(day=5, base_city="上海", items=[depart, resto])],
    )
    _retime_real_food_cards(plan)
    assert resto.start_time is None


# --- 餐卡随时段：下午茶档 + 按动线择卡（2026-11-13 用户「或者下午茶」
#     「所有的餐厅都应该进入午餐卡或者晚餐卡」「按照时间可以决定」）-------


def test_meal_card_slot_has_afternoon_tea_bucket():
    """14:00–16:00 开席算下午茶卡，不再并进午餐卡。"""
    assert _meal_card_slot(_food("v60", "某甜品", time(15, 0))) == "tea"
    assert _meal_card_slot(_food("v61", "某茶馆", time(14, 30))) == "tea"
    assert _meal_card_slot(_food("v62", "晚午饭", time(13, 30))) == "lunch"
    assert _meal_card_slot(_food("v63", "早晚饭", time(16, 0))) == "dinner"


def test_squeezed_lunch_restaurant_moves_to_dinner():
    """老吉士案：11:45–12:30 硬塞在两个景点之间（晚饭卡整晚空着）→ 改晚餐卡。"""
    sight1 = VisitItem(
        item_id="v1",
        name="东方明珠",
        category="attraction",
        city="上海",
        day=2,
        start_time=time(9, 0),
        end_time=time(11, 45),
        duration_minutes=165,
    )
    sight2 = VisitItem(
        item_id="v2",
        name="豫园",
        category="park",
        city="上海",
        day=2,
        start_time=time(12, 34),
        end_time=time(14, 4),
        duration_minutes=90,
    )
    sight3 = VisitItem(
        item_id="v3",
        name="南京东路步行街",
        category="attraction",
        city="上海",
        day=2,
        start_time=time(14, 38),
        end_time=time(16, 8),
        duration_minutes=90,
    )
    resto = VisitItem(
        item_id="v171",
        name="老吉士酒家（天平路店）",
        poi_id="p1",
        category="food",
        city="上海",
        day=2,
        start_time=time(11, 45),
        end_time=time(12, 30),
        duration_minutes=60,
        opening_hours="11:00-14:30,17:00-21:30",
        pinned=True,
        soft_pin=True,
        curated=True,
    )
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["上海"],
        days=[DayPlan(day=2, base_city="上海", items=[sight1, resto, sight2, sight3])],
    )
    _retime_real_food_cards(plan)
    assert resto.start_time == time(17, 0)
    assert resto.end_time == time(18, 0)  # 原本就被压成 60 分钟，不顺带拉长
    assert _meal_card_slot(resto) == "dinner"


def test_untimed_restaurant_takes_tea_slot_when_lunch_and_dinner_taken():
    """午卡被景点占、晚卡已有餐厅 → 落下午茶卡（所有餐厅都要有卡）。"""
    lunch_sight = VisitItem(
        item_id="v1",
        name="上海博物馆",
        category="museum",
        city="上海",
        day=3,
        start_time=time(11, 0),
        end_time=time(14, 0),
        duration_minutes=180,
    )
    dinner = VisitItem(
        item_id="v200",
        name="绿波廊",
        category="food",
        city="上海",
        day=3,
        start_time=time(18, 30),
        end_time=time(19, 30),
        duration_minutes=60,
        pinned=True,
        soft_pin=True,
    )
    resto = VisitItem(
        item_id="v201",
        name="某甜品店",
        poi_id="p1",
        category="food",
        city="上海",
        day=3,
        start_time=None,
        end_time=None,
        duration_minutes=60,
        opening_hours="10:00-22:00",
        pinned=True,
        soft_pin=True,
        curated=True,
    )
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["上海"],
        days=[DayPlan(day=3, base_city="上海", items=[lunch_sight, dinner, resto])],
    )
    _retime_real_food_cards(plan)
    assert _meal_card_slot(resto) == "tea"
    assert resto.start_time == time(14, 0)


def test_user_pinned_restaurant_time_is_never_retimed():
    """用户手钉的时刻（pinned 且非 soft_pin）绝不因动线复审被挪。"""
    dinner = VisitItem(
        item_id="v200",
        name="绿波廊",
        category="food",
        city="上海",
        day=4,
        start_time=time(18, 30),
        end_time=time(19, 30),
        duration_minutes=60,
        pinned=True,
        soft_pin=True,
    )
    resto = VisitItem(
        item_id="v201",
        name="手钉午市",
        poi_id="p1",
        category="food",
        city="上海",
        day=4,
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        opening_hours="10:00-22:00",
        pinned=True,
        soft_pin=False,
    )
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["上海"],
        days=[DayPlan(day=4, base_city="上海", items=[dinner, resto])],
    )
    _retime_real_food_cards(plan)
    assert resto.start_time == time(12, 0)
    assert resto.end_time == time(13, 0)
