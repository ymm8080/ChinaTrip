# -*- coding: utf-8 -*-
"""R14：打车段独立成卡——打车应该在酒店（晨卡）和去程卡之间（2026-11-21）。

_plan_for_response 下发副本上有 taxi-board- 卡、
session 本体零打车卡；去程卡副本 detail 的
打车行清零、session 侧保留。
"""

from datetime import time as dtime

from app.services.itinerary.legs import (
    TAXI_BOARD_PREFIX,
    annotate_legs,
    attach_outbound_taxi_cards,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)


def _remote_day():
    mt = VisitItem(
        item_id="v1",
        name="慕田峪长城",
        category="historic",
        city="北京",
        day=1,
        location=GeoPoint(lon=116.5598, lat=40.4267),
        start_time=dtime(10, 8),
        end_time=dtime(13, 28),
        duration_minutes=200,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=98,
        access_taxi_minutes=15,
        access_ride_minutes=90,
        access_last_mile_minutes=8,
        access_boarding_stop="前门大街北口",
        access_service_name="前门旅游专线",
        access_depart_times=["07:30", "08:30", "09:30", "10:30"],
        access_return_times=["14:30", "15:30", "16:30"],
    )
    out = VisitItem(
        item_id="access-out-v1",
        name="🚌 去程 · 前门大街北口 → 班车约98分",
        category="transfer",
        city="北京",
        day=1,
        start_time=dtime(8, 30),
        end_time=dtime(10, 8),
        duration_minutes=98,
        synthetic=True,
        access_mode="access",
        address="前门大街北口",
    )
    ret = VisitItem(
        item_id="access-return-v1",
        name="回城",
        category="transfer",
        city="北京",
        day=1,
        start_time=dtime(14, 30),
        end_time=dtime(16, 8),
        duration_minutes=98,
        synthetic=True,
    )
    morning = VisitItem(
        item_id="hotel-morning-d1",
        name="🏨 从酒店出发",
        category="hotel",
        city="北京",
        day=1,
        location=GeoPoint(lon=116.412, lat=39.91),
        start_time=dtime(7, 15),
        end_time=dtime(7, 15),
    )
    return [morning, out, mt, ret], out, mt, ret


def _plan(items):
    return ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
        assumptions=[],
    )


def test_taxi_card_between_morning_and_outbound():
    items, out, mt, ret = _remote_day()
    plan = _plan(items)
    annotate_legs(plan)
    d = out.next_leg_detail or {}
    assert d["taxi_minutes"] > 0 and d["taxi_km"] > 0.05
    attach_outbound_taxi_cards(plan)
    day = plan.days[0]
    ids = [i.item_id for i in day.items]
    assert ids == [
        "hotel-morning-d1",
        "taxi-board-v1",
        "access-out-v1",
        "v1",
        "access-return-v1",
    ]
    taxi = day.items[1]
    assert taxi.category == "transfer" and taxi.synthetic
    assert (taxi.end_time.hour, taxi.end_time.minute) == (8, 30)
    assert taxi.start_time < taxi.end_time
    board = taxi.end_time.hour * 60 + taxi.end_time.minute
    start = taxi.start_time.hour * 60 + taxi.start_time.minute
    assert taxi.duration_minutes == board - start
    assert "打车前往" in taxi.name
    assert "前门大街北口" in taxi.name
    d2 = out.next_leg_detail or {}
    assert d2["taxi_km"] == 0.0 and d2["taxi_minutes"] == 0
    assert d2["taxi_cost"] == 0
    assert d2["service_minutes"] == d["service_minutes"]
    assert d2["departures"] == d["departures"]
    assert d2["depart_time"] == d["depart_time"]


def test_taxi_card_idempotent():
    items, out, mt, ret = _remote_day()
    plan = _plan(items)
    annotate_legs(plan)
    attach_outbound_taxi_cards(plan)
    attach_outbound_taxi_cards(plan)
    taxis = [
        i
        for i in plan.days[0].items
        if str(i.item_id or "").startswith(TAXI_BOARD_PREFIX)
    ]
    assert len(taxis) == 1


def test_no_taxi_card_without_taxi_leg():
    # 乘车点=酒店脚下（km≈0）：无打车段不出卡
    items, out, mt, ret = _remote_day()
    plan = _plan(items)
    annotate_legs(plan)
    mt.access_boarding = None  # canonical 源置空：无打车段
    attach_outbound_taxi_cards(plan)
    left = [
        i
        for i in plan.days[0].items
        if str(i.item_id or "").startswith(TAXI_BOARD_PREFIX)
    ]
    assert not left


def test_taxi_minutes_profile_first_geo_fallback():
    from app.services.itinerary.rules import haversine_km, taxi_leg_min

    items, out, mt, ret = _remote_day()
    plan = _plan(items)
    annotate_legs(plan)
    attach_outbound_taxi_cards(plan)
    taxi = next(
        i
        for i in plan.days[0].items
        if str(i.item_id or "").startswith(TAXI_BOARD_PREFIX)
    )
    assert taxi.duration_minutes == 15  # 档案值优先

    items2, out2, mt2, ret2 = _remote_day()
    mt2.access_taxi_minutes = None
    plan2 = _plan(items2)
    annotate_legs(plan2)
    attach_outbound_taxi_cards(plan2)
    taxi2 = next(
        i
        for i in plan2.days[0].items
        if str(i.item_id or "").startswith(TAXI_BOARD_PREFIX)
    )
    morning_pt = next(
        i
        for i in plan2.days[0].items
        if str(i.item_id or "").startswith("hotel-morning")
    ).location
    km = haversine_km(morning_pt, mt2.access_boarding)
    assert taxi2.duration_minutes == taxi_leg_min(km)
    assert taxi2.duration_minutes == (
        taxi2.end_time.hour * 60
        + taxi2.end_time.minute
        - (taxi2.start_time.hour * 60 + taxi2.start_time.minute)
    )


def test_response_copy_only_session_untouched():
    from app.api.plan import _plan_for_response

    items, out, mt, ret = _remote_day()
    plan = _plan(items)
    annotate_legs(plan)
    session_taxi_km = (out.next_leg_detail or {})["taxi_km"]
    resp = _plan_for_response(plan)
    rd = resp.days[0]
    taxis = [i for i in rd.items if str(i.item_id or "").startswith(TAXI_BOARD_PREFIX)]
    assert len(taxis) == 1
    ids = [i.item_id for i in rd.items]
    # 晨卡恒最前、打车卡紧随其后、然后去程卡
    assert ids.index("hotel-morning-d1") < ids.index("taxi-board-v1")
    assert ids.index("taxi-board-v1") < ids.index("access-out-v1")
    rout = next(i for i in rd.items if i.item_id == "access-out-v1")
    assert (rout.next_leg_detail or {})["taxi_km"] == 0.0
    # session 本体零打车卡 + taxi 字段保留
    assert not [
        i
        for i in plan.days[0].items
        if str(i.item_id or "").startswith(TAXI_BOARD_PREFIX)
    ]
    assert (out.next_leg_detail or {})["taxi_km"] == session_taxi_km
