# -*- coding: utf-8 -*-
"""回城卡时刻（2026-11-16 用户：回城开始=末站散场，绝不可能更早）。"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.legs import RETURN_CARD_PREFIX, attach_return_cards
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem


def _plan_with_stale_return():
    site = VisitItem(
        item_id="v1",
        name="上海万达汽车乐园",
        city="上海",
        day=1,
        category="sight",
        duration_minutes=240,
        location=GeoPoint(lon=121.10, lat=31.15),
        start_time=time(12, 46),
        end_time=time(16, 46),
        next_leg_detail={
            "mode": "taxi",
            "direction": "return",
            "to_city": True,
            "gateway": "",
            "alight": "",
            "next_stop": "酒店",
            "service_minutes": 57,
            "walk_minutes": 0,
            "depart_time": "16:00",  # 早于卡面散场：必须被钳到 16:46
            "arrive_time": "16:57",
            "departures": [],
            "returns": [],
        },
    )
    return ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=[site])],
    )


def test_return_card_never_starts_before_last_stop_ends():
    out = attach_return_cards(_plan_with_stale_return())
    card = next(
        i for i in out.days[0].items if str(i.item_id).startswith(RETURN_CARD_PREFIX)
    )
    assert card.start_time >= time(16, 46)
    assert card.end_time > card.start_time
    detail = card.next_leg_detail or {}
    assert detail.get("depart_time") == "16:46"
    assert detail.get("arrive_time") == "17:43"


def test_return_card_keeps_timetable_departure_when_later():
    plan = _plan_with_stale_return()
    site = plan.days[0].items[0]
    site.next_leg_detail["depart_time"] = "17:30"
    site.next_leg_detail["arrive_time"] = "18:27"
    out = attach_return_cards(plan)
    card = next(
        i for i in out.days[0].items if str(i.item_id).startswith(RETURN_CARD_PREFIX)
    )
    assert card.start_time == time(17, 30)


def _plan_with_lunch_after_site():
    """2026-11-22 大足石刻案：游毕 14:00，午饭占位 14:00-15:00 锚在同址，
    打车回城 depart_time=14:00——回城卡与午饭完全重叠 60 分钟。"""
    site = VisitItem(
        item_id="v-dazu",
        name="大足石刻",
        city="重庆",
        day=5,
        category="sight",
        duration_minutes=300,
        location=GeoPoint(lon=105.71, lat=29.70),
        start_time=time(9, 0),
        end_time=time(14, 0),
        next_leg_detail={
            "mode": "taxi",
            "direction": "return",
            "to_city": True,
            "gateway": "",
            "alight": "",
            "next_stop": "酒店",
            "service_minutes": 107,
            "walk_minutes": 0,
            "depart_time": "14:00",
            "arrive_time": "15:47",
            "departures": [],
            "returns": [],
        },
    )
    lunch = VisitItem(
        item_id="meal-lunch-5",
        name="午餐",
        city="重庆",
        day=5,
        category="food",
        duration_minutes=60,
        location=GeoPoint(lon=105.71, lat=29.70),
        start_time=time(14, 0),
        end_time=time(15, 0),
    )
    return ItineraryPlan(
        itinerary_id="t",
        cities=["重庆"],
        days=[DayPlan(day=5, base_city="重庆", items=[site, lunch])],
    )


def test_return_card_yields_to_same_venue_lunch_placeholder():
    # 2026-11-22 用户拍板「回程腿给午饭让位、顺延到 15:00-16:47」：
    # 回城卡开始让到同址午饭占位结束之后，到达时刻整体顺延。
    out = attach_return_cards(_plan_with_lunch_after_site())
    card = next(
        i for i in out.days[0].items if str(i.item_id).startswith(RETURN_CARD_PREFIX)
    )
    assert card.start_time == time(15, 0)
    assert card.end_time == time(16, 47)
    assert card.start_time >= time(15, 0)
    detail = card.next_leg_detail or {}
    assert detail.get("depart_time") == "15:00"
    assert detail.get("arrive_time") == "16:47"


def test_return_card_no_yield_when_lunch_already_before_visit_end():
    # 午饭排在游玩结束之前（先午餐后游览已换序的日）→ 回城卡照常吃
    # depart_time，不让位。
    plan = _plan_with_lunch_after_site()
    lunch = plan.days[0].items[1]
    lunch.start_time = time(11, 30)
    lunch.end_time = time(12, 30)
    out = attach_return_cards(plan)
    card = next(
        i for i in out.days[0].items if str(i.item_id).startswith(RETURN_CARD_PREFIX)
    )
    assert card.start_time == time(14, 0)
    assert card.end_time == time(15, 47)
