# -*- coding: utf-8 -*-
"""R50：点选返程班次优先（远郊回程必须在点选班次发车，不让位给游后同址餐）。"""

from datetime import time

import pytest

from app.services.itinerary import legs as legs_mod
from app.services.itinerary import rules as rules_mod
from app.services.itinerary.legs import annotate_legs, attach_return_cards
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem

GATEWAY = GeoPoint(lon=116.3982, lat=39.8988)  # 前门大街北口


@pytest.fixture(autouse=True)
def _shuttle_profile(monkeypatch):
    """慕田峪=班次档案：专线 98 分、候车 60、走回乘车点 8 分钟。"""

    def _profile(item):
        if getattr(item, "access_mode", None) == "shuttle":
            return ("shuttle", GATEWAY, 98, 60, 8)
        return (None, None, None, None, None)

    monkeypatch.setattr(legs_mod, "_access_profile", _profile)
    monkeypatch.setattr(rules_mod, "_access_profile", _profile)
    yield


def _mutianyu(*, end: time, chosen: str | None = "15:30") -> VisitItem:
    return VisitItem(
        item_id="v8",
        name="慕田峪长城",
        category="historic",
        city="北京",
        day=3,
        start_time=time(12, 8),
        end_time=end,
        duration_minutes=int((end.hour * 60 + end.minute) - (12 * 60 + 8)),
        location=GeoPoint(lon=116.5598, lat=40.4267),
        access_mode="shuttle",
        access_boarding_stop="前门大街北口",
        access_service_name="前门旅游专线",
        access_service_minutes=98,
        access_ride_minutes=90,
        access_last_mile_minutes=8,
        access_taxi_minutes=15,
        access_depart_times=["07:30", "08:30", "09:30", "10:30"],
        access_return_times=["14:30", "15:30", "16:30"],
        access_chosen_return=chosen,
    )


def _lunch(*, start: time, end: time) -> VisitItem:
    return VisitItem(
        item_id="meal-lunch-3",
        name="午餐",
        category="food",
        city="北京",
        day=3,
        start_time=start,
        end_time=end,
        duration_minutes=int(
            (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        ),
        anchor_from_prev=True,
        anchor_location=GeoPoint(lon=116.5598, lat=40.4267),
        access_mode="shuttle",
        access_boarding_stop="前门大街北口",
        access_service_name="前门旅游专线",
        access_service_minutes=98,
        access_ride_minutes=90,
        access_last_mile_minutes=8,
        access_depart_times=["07:30", "08:30", "09:30", "10:30"],
        access_return_times=["14:30", "15:30", "16:30"],
    )


def _plan(site: VisitItem, meal: VisitItem) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[
            DayPlan(
                day=3,
                base_city="北京",
                items=[
                    VisitItem(
                        item_id="access-out-v8",
                        name="🚌 去程",
                        category="transfer",
                        city="北京",
                        day=3,
                        start_time=time(9, 0),
                        end_time=time(10, 38),
                        duration_minutes=98,
                        synthetic=True,
                    ),
                    site,
                    meal,
                    VisitItem(
                        item_id="meal-dinner-3",
                        name="晚饭",
                        category="food",
                        city="北京",
                        day=3,
                        start_time=time(18, 38),
                        end_time=time(19, 23),
                        duration_minutes=45,
                        anchor_from_prev=True,
                    ),
                ],
            )
        ],
        assumptions=[],
    )


def test_chosen_return_trims_visit_and_moves_post_visit_meal():
    """点选 15:30：游览截到 15:22（留 8 分钟走回乘车点），游后同址午餐挪到游前。"""
    plan = _plan(_mutianyu(end=time(16, 8)), _lunch(start=time(16, 8), end=time(17, 8)))
    annotate_legs(plan)
    site = next(i for i in plan.days[0].items if i.item_id == "v8")
    meal = next(i for i in plan.days[0].items if i.item_id == "meal-lunch-3")
    assert site.end_time == time(15, 22), site.end_time
    # 游览 12:08 起、餐 60 分钟 → 挪到 11:08-12:08（前一张去程卡 10:38 收尾）
    assert meal.start_time == time(11, 8), meal.start_time
    assert meal.end_time == time(12, 8), meal.end_time
    det = site.next_leg_detail or {}
    assert det.get("direction") == "return"
    assert det.get("depart_time") == "15:30", det.get("depart_time")
    assert det.get("arrive_time") == "17:08", det.get("arrive_time")


def test_chosen_return_card_sits_before_dinner():
    """回城卡按点选班次出时刻，排在游览之后、晚饭之前（不再被游后餐推到 19:23）。"""
    plan = _plan(_mutianyu(end=time(16, 8)), _lunch(start=time(16, 8), end=time(17, 8)))
    annotate_legs(plan)
    out = attach_return_cards(plan)
    ids = [i.item_id for i in out.days[0].items]
    card = next(i for i in out.days[0].items if i.item_id == "access-return-v8")
    assert card.start_time == time(15, 30), card.start_time
    assert card.end_time == time(17, 8), card.end_time
    assert ids.index("access-return-v8") < ids.index("meal-dinner-3"), ids
    # 接驳格式：班次名 + 步行 + 车上分钟（不是市区打车那一行）
    det = card.next_leg_detail or {}
    assert det.get("service_name", "").startswith("前门旅游专线")
    assert det.get("walk_minutes") == 8
    assert det.get("service_minutes") == 90


def test_without_chosen_return_meal_yield_still_applies():
    """未点选班次时，2026-11-22 大足口径不变：回程给同址游后餐让位。"""
    plan = _plan(
        _mutianyu(end=time(16, 8), chosen=None),
        _lunch(start=time(16, 8), end=time(17, 8)),
    )
    annotate_legs(plan)
    site = next(i for i in plan.days[0].items if i.item_id == "v8")
    assert site.end_time == time(16, 8), site.end_time
    meal = next(i for i in plan.days[0].items if i.item_id == "meal-lunch-3")
    assert meal.start_time == time(16, 8), meal.start_time
    out = attach_return_cards(plan)
    card = next(i for i in out.days[0].items if i.item_id == "access-return-v8")
    # 让位：回城从餐后 17:08 起
    assert card.start_time >= time(17, 8), card.start_time
