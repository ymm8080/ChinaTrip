# -*- coding: utf-8 -*-
"""腿的展示时间/成本（2026-11-16 用户拍板「网页正确显示时间和成本预估」）。

锁定：①城市出租车价目表估算；②接驳链按链值+接驳票价（打车到乘车点+默认票价）；
③普通城市对走打车模型；④≤1.5km 步行不收费。
"""

from datetime import time

from app.services.itinerary.fares import access_fare_estimate, estimate_taxi_fare
from app.services.itinerary.legs import annotate_legs
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)


def _v(item_id, name, lon, lat, **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city="北京",
        day=1,
        duration_minutes=60,
        category="sight",
        location=GeoPoint(lon=lon, lat=lat),
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    base.update(kw)
    return VisitItem(**base)


def test_city_taxi_fare_table():
    assert estimate_taxi_fare("北京", 10) == 29  # 13 + 7*2.3
    assert estimate_taxi_fare("成都", 2) == 9
    assert estimate_taxi_fare("不存在的城市", 10) == 24  # default 10 + 7*2
    assert estimate_taxi_fare("北京", 1) == 13
    assert access_fare_estimate("shuttle") == 20
    assert access_fare_estimate("ferry") == 10
    assert access_fare_estimate("train") == 5
    assert access_fare_estimate("") == 0


def test_annotate_legs_access_chain_time_and_fare():
    a = _v("td", "天安门广场", 116.4103, 39.9115)
    b = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.4103, lat=39.9115),
        access_service_minutes=108,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[a, b])],
        assumptions=[],
    )
    annotate_legs(plan)
    assert a.next_leg_mode == "access"
    assert a.next_leg_minutes == 126  # 0 + 10 + 108 + 8
    assert a.next_leg_cost_cny == 33  # 起步价 13 + 接驳 20
    assert a.next_leg_cost_note


def test_annotate_legs_taxi_and_walk():
    a = _v("td", "天安门广场", 116.4103, 39.9115)
    b = _v("gg", "故宫博物院", 116.4097, 39.9255)
    c = _v("x", "街角", 116.4120, 39.9120)
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[
            DayPlan(day=1, base_city="北京", items=[a, b]),
            DayPlan(day=2, base_city="北京", items=[c]),
        ],
        assumptions=[],
    )
    annotate_legs(plan)
    assert a.next_leg_mode == "taxi"
    assert a.next_leg_minutes == 30  # 1.87km → floor 30
    assert a.next_leg_cost_cny == 13
    # b → 无下一站：清空
    assert b.next_leg_minutes is None
