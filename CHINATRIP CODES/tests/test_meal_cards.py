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
)
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem


def _food(item_id: str, name: str, start: time | None, dur: int = 60) -> VisitItem:
    end = (
        None
        if start is None
        else time((start.hour * 60 + start.minute + dur) // 60 % 24,
                  (start.minute + dur) % 60)
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
        item_id="v9", name="外滩", category="attraction", city="上海", day=1,
        start_time=time(18, 0), duration_minutes=60,
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
    untimed = DayPlan(
        day=1, base_city="上海", items=[_food("v35", "某餐厅", None)]
    )
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
    assert any("撤掉重复的自动补餐" in a and "老吉士" in a
               for a in plan.assumptions)


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
