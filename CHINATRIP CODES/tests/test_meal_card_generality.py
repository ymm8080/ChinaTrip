# -*- coding: utf-8 -*-
"""餐卡绑定的通用性回归（2026-11-13 用户「是通用 FIXING 吗」）。

绑定规则不认城市/店名：只看卡窗（午 11:30-12:30 / 茶 14:00-16:00 /
晚 17:00-20:30）、系统餐 id 与同址景点时刻。下面用上海/北京/成都/广州
的不同宿主、不同餐别、有无坐标来说明。
"""

from datetime import time

import pytest

from app.services.agent.plan import _bind_real_food_to_cards, _meal_card_slot
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem


def _item(
    iid: str,
    name: str,
    cat: str,
    city: str,
    start: time,
    dur: int,
    *,
    day: int = 1,
    loc: GeoPoint | None = None,
    **kw,
) -> VisitItem:
    m = start.hour * 60 + start.minute
    return VisitItem(
        item_id=iid,
        name=name,
        category=cat,
        city=city,
        day=day,
        location=loc,
        start_time=start,
        end_time=time((m + dur) // 60 % 24, (m + dur) % 60),
        duration_minutes=dur,
        **kw,
    )


def _plan(items: list[VisitItem], city: str, day: int = 1) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it1",
        cities=[city],
        days=[DayPlan(day=day, base_city=city, items=list(items))],
    )


@pytest.mark.parametrize(
    ("city", "host_name"),
    [("上海", "豫园"), ("北京", "故宫博物院"), ("成都", "宽窄巷子")],
)
def test_lunch_card_follows_same_venue_host_end(city: str, host_name: str):
    """同址景点 09:00-12:00 收尾 → 午卡贴 12:00（不是写死 12:30）。"""
    loc = GeoPoint(lon=116.4, lat=39.9)
    host = _item("v1", host_name, "attraction", city, time(9, 0), 180, loc=loc)
    resto = _item(
        "food-d1-lunch-1", "同址餐厅", "food", city, time(16, 15), 30, loc=loc,
        soft_pin=True,
    )
    plan = _plan([host, resto], city)
    _bind_real_food_to_cards(plan)
    assert _meal_card_slot(resto) == "lunch"
    assert resto.start_time == time(12, 0)


def test_system_dinner_id_stays_dinner_when_drifted_to_noon():
    """成都 day3 的 food-d3-dinner-1 被漂到 12:00，仍归晚卡、落 17:30。"""
    resto = _item(
        "food-d3-dinner-1", "某晚宴", "food", "成都", time(12, 0), 60,
        day=3, soft_pin=True,
    )
    plan = _plan([resto], "成都", day=3)
    _bind_real_food_to_cards(plan)
    assert _meal_card_slot(resto) == "dinner"
    assert resto.start_time == time(17, 30)


def test_tea_restaurant_inside_window_is_not_moved():
    """北京 15:30 的茶馆本就在下午茶窗内，零改动。"""
    resto = _item("v2", "某茶馆", "food", "北京", time(15, 30), 60)
    plan = _plan([resto], "北京")
    assert _bind_real_food_to_cards(plan) == []
    assert resto.start_time == time(15, 30)


def test_one_card_one_restaurant_prefers_user_card():
    """同一天两张午卡餐厅：用户卡保留，系统自动补餐撤除。"""
    user = _item("v9", "用户午市", "food", "上海", time(12, 0), 90)
    auto = _item(
        "food-d2-lunch-1", "系统午市", "food", "上海", time(16, 15), 30,
        day=2, soft_pin=True,
    )
    plan = _plan([user, auto], "上海", day=2)
    notes = _bind_real_food_to_cards(plan)
    assert [i.name for i in plan.days[0].items] == ["用户午市"]
    assert any("撤掉重复餐卡" in n for n in notes)


def test_lunch_without_location_falls_back_to_noon():
    """无坐标可贴 → 回正窗 12:00，仍在 [11:30,12:30] 内。"""
    resto = _item(
        "food-d1-lunch-1", "无坐标餐厅", "food", "上海", time(16, 15), 30,
        soft_pin=True,
    )
    plan = _plan([resto], "上海")
    _bind_real_food_to_cards(plan)
    assert resto.start_time == time(12, 0)
