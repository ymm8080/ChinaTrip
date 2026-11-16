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

class _FakeStore:
    """假班次源（access_services.configure_store 的入参形状）。"""

    def __init__(self, rows):
        self._rows = rows

    def access_services(self, cities=None):
        return list(self._rows)


def _svc_row(**kw):
    row = dict(
        city="北京",
        poi_name="慕田峪长城",
        mode="shuttle",
        service_name="前门旅游专线",
        operator="北京旅游集散中心",
        boarding_stop="前门大街北口",
        boarding_lon=116.3982,
        boarding_lat=39.8988,
        alight_stop="慕田峪长城 P1/P4 停车场",
        outbound_times=["07:30", "08:30", "09:30", "10:30"],
        outbound_first=None,
        outbound_last=None,
        outbound_frequency_minutes=None,
        ride_minutes=90,
        return_times=["14:30", "15:30", "16:30"],
        return_first=None,
        return_last="16:30",
        return_frequency_minutes=None,
        return_ride_minutes=None,
        return_arrive_last=None,
        fare_cny=80.0,
        fare_kind="round_trip",
        fare_note="往返车费 80 元",
        ticket_channel=None,
        ticket_url="https://en.mutianyugreatwall.com/pdf/one-day",
        last_mile_minutes=8,
        note=None,
        note_en=None,
        source="official:mutianyugreatwall",
        source_url="https://en.mutianyugreatwall.com/pdf/one-day",
        official_url="https://en.mutianyugreatwall.com/pdf/one-day",
        official_status="verified",
        window_source="official",
        fare_source="official",
        poi_name_en="Mutianyu Great Wall",
        service_name_en="Qianmen Tourist Line",
        boarding_stop_en="Qianmen Street north entrance",
    )
    row.update(kw)
    return row


def test_fastest_plan_picks_earliest_arrival_at_shuttle_stop():
    """用户拍板 MOST TIME SAVING METHOD：到 08:46 上车后选「最早到景区」的一班。"""
    from app.services import access_services

    slow = _svc_row(service_name="慢线", outbound_times=["09:00"], ride_minutes=150)
    fast = _svc_row(service_name="快线", outbound_times=["08:30", "09:30"], ride_minutes=90)
    access_services.configure_store(_FakeStore([slow, fast]))
    try:
        got = access_services.fastest_plan("北京", "慕田峪长城", 8 * 60 + 46)
    finally:
        access_services.configure_store(None)
    assert got is not None
    depart, ride, last, wait = got
    assert depart == 9 * 60 + 30   # 08:30 已发车，赶 09:30（慢线 09:00 到得更晚）
    assert ride == 90
    assert last == 8
    assert wait == 44


def test_morning_hotel_chain_uses_checkout_time_and_timetable():
    """晨卡按 08:30 离店打接驳链：打车 0.98km → 09:30 班次 → 11:08 到景区。"""
    from app.services import access_services
    from app.services.itinerary import rules

    access_services.configure_store(_FakeStore([_svc_row()]))
    hotel = VisitItem(
        item_id="hotel-morning-d1",
        name="🏨 从酒店出发",
        city="北京",
        day=1,
        category="hotel",
        duration_minutes=30,
        location=None,
        anchor_location=GeoPoint(lon=116.4074, lat=39.9042),
        start_time=time(8, 30),
        end_time=time(9, 0),
    )
    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_depart_times=["07:30", "08:30", "09:30", "10:30"],
    )
    try:
        br = rules.access_breakdown(hotel, mt)
    finally:
        access_services.configure_store(None)
    assert br["board"] == 8 * 60 + 46   # 08:30 + 16 分钟打车
    assert br["depart"] == 9 * 60 + 30
    assert br["wait"] == 44
    assert br["minutes"] == 16 + 44 + 90 + 8   # 158


def test_access_leg_detail_has_taxi_leg_shuttle_and_urls():
    """网页腿行要看清：打车到乘车点（距离+时间）→ 专线车程 → 步行 + 班次/预约 URL。"""
    a = VisitItem(
        item_id="hotel-morning-d1",
        name="🏨 从酒店出发",
        city="北京",
        day=1,
        category="hotel",
        duration_minutes=30,
        location=None,
        anchor_location=GeoPoint(lon=116.4074, lat=39.9042),
        start_time=time(8, 30),
        end_time=time(9, 0),
    )
    b = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_depart_times=["07:30", "08:30", "09:30", "10:30"],
        access_return_times=["14:30", "15:30", "16:30"],
        access_service_name="前门旅游专线（前门大街北口）",
        access_operator="北京旅游集散中心",
        access_boarding_stop="前门大街北口（北京旅游集散中心发车点）",
        access_alight_stop="慕田峪长城 P1/P4 停车场",
        access_fare_text="往返车费 80 元",
        access_ticket_url="https://en.mutianyugreatwall.com/pdf/one-day",
        access_official_url="https://en.mutianyugreatwall.com/pdf/one-day",
        booking_url="https://en.mutianyugreatwall.com/reservation-center/tickets",
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[a, b])],
        assumptions=[],
    )
    annotate_legs(plan)
    detail = a.next_leg_detail
    assert detail is not None
    assert detail["mode"] == "access"
    assert detail["gateway"].startswith("前门大街北口")
    assert detail["alight"].startswith("慕田峪长城")
    assert detail["service_name"].startswith("前门旅游专线")
    assert detail["departures"] == ["07:30", "08:30", "09:30", "10:30"]
    assert detail["returns"] == ["14:30", "15:30", "16:30"]
    assert detail["board_time"] == "08:46"
    assert detail["depart_time"] == "09:30"
    assert detail["arrive_time"] == "11:08"
    assert detail["taxi_km"] > 0.5
    assert detail["taxi_minutes"] >= 16
    assert detail["service_minutes"] == 90
    assert detail["walk_minutes"] == 8
    assert detail["taxi_cost"] > 0 and detail["access_cost"] == 20
    assert "mutianyugreatwall" in detail["booking_url"]
    assert "mutianyugreatwall" in detail["official_url"]
    assert "80" in detail["fare_text"]
