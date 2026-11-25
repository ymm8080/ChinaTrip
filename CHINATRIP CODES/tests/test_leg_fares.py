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
    fast = _svc_row(
        service_name="快线", outbound_times=["08:30", "09:30"], ride_minutes=90
    )
    access_services.configure_store(_FakeStore([slow, fast]))
    try:
        got = access_services.fastest_plan("北京", "慕田峪长城", 8 * 60 + 46)
    finally:
        access_services.configure_store(None)
    assert got is not None
    depart, ride, last, wait = got
    assert depart == 9 * 60 + 30  # 08:30 已发车，赶 09:30（慢线 09:00 到得更晚）
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
    assert br["board"] == 8 * 60 + 46 + 15  # 08:30 + 16 打车 + 15′ 早高峰 = 09:01
    assert br["rush"] == 15
    assert br["depart"] == 9 * 60 + 30
    assert br["wait"] == 44 - 15  # 早高峰吃进候车：09:30 − 09:01
    assert br["minutes"] == 31 + 29 + 90 + 8  # 158（班次不变，候车被早高峰吃掉）


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
        # 裸域名（库里真实形态）
        booking_url="en.mutianyugreatwall.com/reservation-center/tickets",
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
    assert detail["board_time"] == "09:01"
    assert detail["next_item_id"] == "mt"  # 去程卡上的返程 chips 按下一站卡回推
    assert detail["depart_time"] == "09:30"
    assert detail["arrive_time"] == "11:08"
    assert detail["taxi_km"] > 0.5
    assert detail["taxi_minutes"] >= 31
    assert "早高峰" in detail["taxi_rush_note"]
    assert detail["service_minutes"] == 90
    assert detail["walk_minutes"] == 8
    # 无班次库行=按模式估算
    assert detail["taxi_cost"] > 0 and detail["access_cost"] == 20
    assert detail["booking_url"].startswith("https://")
    assert detail["booking_url"] == (
        "https://en.mutianyugreatwall.com/reservation-center/tickets"
    )
    assert "mutianyugreatwall" in detail["official_url"]
    assert "80" in detail["fare_text"]


def test_service_options_rank_fewer_transfers_then_shorter():
    """多方式分块：默认推荐=换乘少，其次时间短（2026-11-16 用户拍板）。

    2026-11-23 用户拍板「any bus should be replaced by taxi」后，换乘选项改用
    铁路接驳（非 bus）——常规公交已在 ``services_for`` 单点剔除，不再进候选。
    """
    from app.services import access_services

    direct_slow = _svc_row(
        service_name="前门旅游专线",
        mode="shuttle",
        boarding_stop="前门发车中心",
        ride_minutes=100,
        fare_cny=50.0,
    )
    transfer_fast = _svc_row(
        service_name="市郊铁路 S2线 → 八达岭接驳车（1 次换乘）",
        mode="train",
        boarding_stop="黄土店站",
        ride_minutes=60,
        fare_cny=10.0,
    )
    access_services.configure_store(_FakeStore([transfer_fast, direct_slow]))
    try:
        opts = access_services.service_options(
            "北京",
            "慕田峪长城",
            board_minutes=9 * 60,
            ride_fallback=90,
            last_fallback=8,
            wait_fallback=10,
            taxi_minutes=lambda coords: 20 if coords else 0,
        )
    finally:
        access_services.configure_store(None)
    assert [o["service_name"] for o in opts] == [
        "前门旅游专线",
        "市郊铁路 S2线 → 八达岭接驳车（1 次换乘）",
    ]
    assert opts[0]["recommended"] is True
    assert opts[0]["transfers"] == 0
    assert opts[1]["transfers"] == 1
    assert opts[0]["has_timetable"] is True
    assert opts[0]["boarding_stop"] == "前门发车中心"
    assert opts[0]["taxi_minutes"] == 20
    assert opts[0]["depart"] == "09:30"  # 09:20 到乘车点，赶 09:30 班
    assert opts[0]["wait_minutes"] == 10
    assert opts[0]["total_minutes"] == 20 + 10 + 100 + 8


def test_access_breakdown_multi_mode_options_and_clear_gateway():
    """八达岭案：多方式行拆开后，腿按推荐项算，明细带 options 且乘车点清晰。"""
    from app.services import access_services

    train = _svc_row(
        poi_name="八达岭长城",
        service_name="市郊铁路 S2线",
        mode="train",
        boarding_stop="黄土店站",
        boarding_lon=116.37,
        boarding_lat=40.05,
        alight_stop="八达岭站",
        ride_minutes=70,
        fare_cny=6.0,
        last_mile_minutes=10,
        outbound_times=["07:26", "08:26", "09:26"],
    )
    coach = _svc_row(
        poi_name="八达岭长城",
        service_name="北京旅游集散中心直通车",
        mode="shuttle",
        boarding_stop="德胜门站",
        boarding_lon=116.385,
        boarding_lat=39.949,
        alight_stop="八达岭站",
        ride_minutes=80,
        fare_cny=12.0,
        last_mile_minutes=10,
        outbound_times=["06:30", "07:30", "08:30"],
    )
    # 常规公交（mode=bus）：2026-11-23 用户拍板「any bus should be replaced by
    # taxi」——进档案即被剔除，下面的断言钉住它绝不作为 option 露出。
    bus = _svc_row(
        poi_name="八达岭长城",
        service_name="877路",
        mode="bus",
        boarding_stop="北土城站",
        boarding_lon=116.402,
        boarding_lat=39.978,
        alight_stop="八达岭站",
        ride_minutes=90,
        fare_cny=12.0,
        last_mile_minutes=10,
        outbound_times=["06:30", "07:30", "08:30"],
    )
    access_services.configure_store(_FakeStore([train, coach, bus]))
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
        "bd",
        "八达岭长城",
        116.02,
        40.36,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.397708, lat=39.898894),
        access_service_minutes=91,
        access_wait_minutes=10,
        access_last_mile_minutes=3,
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[a, b])],
        assumptions=[],
    )
    try:
        annotate_legs(plan)
    finally:
        access_services.configure_store(None)
    detail = a.next_leg_detail
    opts = detail["options"]
    assert len(opts) == 2
    # 常规公交不出现（2026-11-23 拍板一律改打车）
    assert "877路" not in [o["service_name"] for o in opts]
    assert opts[0]["recommended"] is True
    # 乘车点是清晰单站名（不是三站拼一串），且与推荐块一致
    assert detail["gateway"] == opts[0]["boarding_stop"]
    assert " / " not in (detail["gateway"] or "")
    assert detail["service_name"] == opts[0]["service_name"]
    assert detail["options"][0]["boarding_stop"] in ("黄土店站", "德胜门站")
    # 腿分钟 = 推荐项 打车+候车+车程+步行（同口径）
    assert a.next_leg_minutes == (
        opts[0]["taxi_minutes"]
        + opts[0]["wait_minutes"]
        + opts[0]["ride_minutes"]
        + opts[0]["last_mile_minutes"]
    )
    assert a.next_leg_mode == "access"
    # 每块都有打车估算与购票/官网链接字段
    for o in opts:
        assert o["taxi_minutes"] >= 0
        assert "taxi_cost" in o
        assert "booking_url" in o and "official_url" in o


def test_dinner_placeholder_anchors_to_hotel_and_return_leg_from_scenic():
    """晚饭占位不留在景区：锚到下一站（酒店），回城腿从景区散场起算。"""
    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        start_time=time(11, 8),
        end_time=time(14, 8),
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_ride_minutes=90,
        access_return_times=["14:30", "15:30", "16:30"],
        access_service_name="前门旅游专线（前门大街北口）",
        access_boarding_stop="前门大街北口（北京旅游集散中心发车点）",
        access_alight_stop="慕田峪长城 P1/P4 停车场",
    )
    dinner = VisitItem(
        item_id="food-dinner-ph-d1",
        name="晚饭（自由安排）",
        category="food",
        city="北京",
        day=1,
        duration_minutes=60,
        anchor_from_prev=True,
        start_time=time(19, 0),
        end_time=time(20, 0),
    )
    night = VisitItem(
        item_id="hotel-night-d1",
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="北京",
        day=1,
        duration_minutes=60,
        location=GeoPoint(lon=116.4074, lat=39.9042),
        address="北京市东城区某酒店",
        start_time=time(20, 30),
        end_time=time(21, 30),
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[mt, dinner, night])],
        assumptions=[],
    )
    annotate_legs(plan)
    # 晚饭锚到酒店（下一站），不再留在景区
    assert dinner.address == "北京市东城区某酒店"
    assert dinner.anchor_location is not None
    assert mt.next_leg_mode == "access"
    detail = mt.next_leg_detail
    assert detail is not None and detail["direction"] == "return"
    assert detail["depart_time"] == "14:30"  # 14:08 散场 + 8 分钟 → 14:16 → 14:30
    assert detail["next_stop"] == "晚饭（自由安排）"
    assert mt.next_leg_minutes > 90
    # 晚饭→夜卡同址（都在酒店）：不成腿
    assert dinner.next_leg_minutes is None


def test_tail_return_when_dinner_and_night_stay_on_site():
    """用户的真实形状：慕田峪 → 午饭/晚饭锚在景区 → 夜卡无坐标。

    晚饭继承班次档案也不能把回城链判成去程；夜卡没坐标也要在慕田峪卡上
    出回城段（2026-11-16 用户拍板「游玩时间结束后应该有一个回城腿」）。
    """
    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        start_time=time(10, 8),
        end_time=time(13, 8),
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_ride_minutes=90,
        access_return_times=["14:30", "15:30", "16:30"],
        access_service_name="前门旅游专线（前门大街北口）",
        access_boarding_stop="前门大街北口（北京旅游集散中心发车点）",
        access_alight_stop="慕田峪长城 P1/P4 停车场",
    )
    lunch = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        category="food",
        city="北京",
        day=1,
        duration_minutes=60,
        anchor_from_prev=True,
        start_time=time(13, 8),
        end_time=time(14, 8),
    )
    dinner = VisitItem(
        item_id="food-dinner-ph-d1",
        name="晚饭（自由安排）",
        category="food",
        city="北京",
        day=1,
        duration_minutes=90,
        anchor_from_prev=True,
        start_time=time(19, 0),
        end_time=time(20, 30),
    )
    night = VisitItem(
        item_id="hotel-night-d1",
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="北京",
        day=1,
        duration_minutes=60,
        start_time=time(21, 0),
        end_time=time(22, 0),
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[mt, lunch, dinner, night])],
        assumptions=[],
    )
    annotate_legs(plan)
    assert mt.next_leg_mode == "access"
    detail = mt.next_leg_detail
    assert detail is not None and detail["direction"] == "return"
    assert detail["to_city"] is True
    assert detail["depart_time"] == "14:30"  # 13:08 散场 + 8 分钟 → 14:30 班
    assert detail["gateway"].startswith("慕田峪长城")
    assert detail["alight"].startswith("前门大街北口")
    # 同址占位卡都不显示重复腿
    assert lunch.next_leg_minutes is None
    assert dinner.next_leg_minutes is None


def test_tail_return_chain_when_remote_is_last_of_day():
    """当天最后一站是班次点（用户行程 Day1 只有慕田峪）：也出回城段。"""
    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        start_time=time(11, 8),
        end_time=time(14, 8),
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_ride_minutes=90,
        access_return_times=["14:30", "15:30", "16:30"],
        access_service_name="前门旅游专线（前门大街北口）",
        access_boarding_stop="前门大街北口（北京旅游集散中心发车点）",
        access_alight_stop="慕田峪长城 P1/P4 停车场",
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[mt])],
        assumptions=[],
    )
    annotate_legs(plan)
    assert mt.next_leg_mode == "access"
    detail = mt.next_leg_detail
    assert detail is not None
    assert detail["direction"] == "return"
    assert detail["to_city"] is True
    assert detail["gateway"].startswith("慕田峪长城")
    assert detail["alight"].startswith("前门大街北口")
    assert detail["board_time"] == "14:16"  # 14:08 散场 + 8 分钟走回乘车点
    assert detail["depart_time"] == "14:30"
    assert (
        detail["arrive_time"] == "16:08"
    )  # R38：含下客步行（与 materialize 卡面同口径）
    assert mt.next_leg_minutes == 8 + (14 * 60 + 30 - (14 * 60 + 8 + 8)) + 90
    assert mt.next_leg_cost_cny == access_fare_estimate("shuttle")


def test_return_leg_shuttle_chain_from_remote_stop():
    """回城腿（2026-11-16 用户拍板「回城也是一样的接驳三段」）：慕田峪 →
    市区走返向链（步行回乘车点 → 返程班 → 市区落点打车），不是打车直线。"""
    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        start_time=time(11, 8),
        end_time=time(12, 38),
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_ride_minutes=90,
        access_return_times=["14:30", "15:30", "16:30"],
        access_service_name="前门旅游专线（前门大街北口）",
        access_operator="北京旅游集散中心",
        access_boarding_stop="前门大街北口（北京旅游集散中心发车点）",
        access_alight_stop="慕田峪长城 P1/P4 停车场",
        access_fare_text="往返车费 80 元",
    )
    wfj = _v(
        "wfj",
        "王府井",
        116.4109,
        39.9097,
        start_time=time(15, 8),
        end_time=time(16, 38),
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[mt, wfj])],
        assumptions=[],
    )
    annotate_legs(plan)
    assert mt.next_leg_mode == "access"
    detail = mt.next_leg_detail
    assert detail is not None
    assert detail["direction"] == "return"
    assert detail["gateway"].startswith("慕田峪长城")
    assert detail["alight"].startswith("前门大街北口")
    assert detail["next_stop"] == "王府井"
    assert detail["departures"] == ["14:30", "15:30", "16:30"]
    assert detail["board_time"] == "12:46"  # 12:38 散场 + 8 分钟走回乘车点
    assert detail["depart_time"] == "14:30"  # 最快返程班
    assert (
        detail["arrive_time"] == "16:08"
    )  # 14:30 + 90 车程 + 8 下客步行（R38 同口径）
    assert detail["walk_minutes"] == 8
    assert detail["taxi_km"] < 5  # 市区落点→王府井，不是 58km 打车直线
    assert mt.next_leg_minutes == (
        8 + (14 * 60 + 30 - (12 * 60 + 38 + 8)) + 90 + detail["taxi_minutes"]
    )
    assert mt.next_leg_cost_cny == (
        estimate_taxi_fare("北京", detail["taxi_km"]) + access_fare_estimate("shuttle")
    )


def test_anchored_meal_inherits_access_and_return_chain():
    """锚在班次点上的占位餐卡继承接驳档案：回城腿挂餐卡上仍是接驳三段，
    排期隔隙同口径吃返向链；锚离开班次点档案即清（幂等重算）。"""
    from app.services.itinerary import rules
    from app.services.itinerary.legs import resolve_meal_anchors

    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        start_time=time(11, 8),
        end_time=time(12, 38),
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_ride_minutes=90,
        access_return_times=["14:30", "15:30", "16:30"],
        access_service_name="前门旅游专线（前门大街北口）",
        access_operator="北京旅游集散中心",
        access_boarding_stop="前门大街北口（北京旅游集散中心发车点）",
        access_alight_stop="慕田峪长城 P1/P4 停车场",
        access_fare_text="往返车费 80 元",
    )
    lunch = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        category="food",
        city="北京",
        day=1,
        duration_minutes=60,
        anchor_from_prev=True,
        start_time=time(12, 38),
        end_time=time(13, 38),
    )
    wfj = _v(
        "wfj",
        "王府井",
        116.4109,
        39.9097,
        start_time=time(15, 8),
        end_time=time(16, 38),
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[mt, lunch, wfj])],
        assumptions=[],
    )
    resolve_meal_anchors(plan)
    assert lunch.access_mode == "shuttle"
    assert lunch.access_return_times == ["14:30", "15:30", "16:30"]
    br = rules.access_breakdown(lunch, wfj)
    assert br is not None and br["direction"] == "return"
    assert br["board"] == 13 * 60 + 46  # 13:38 散场 + 8 分钟走回乘车点
    assert br["depart"] == 14 * 60 + 30
    gap = rules.travel_gap_needed(lunch, wfj)
    assert gap == 8 + 44 + 90 + br["taxi_minutes"]  # 链值，不是打车下限
    annotate_legs(plan)
    # 回城链挂回景区卡（占位餐卡不重复显示）
    detail = mt.next_leg_detail
    assert detail is not None and detail["direction"] == "return"
    assert detail["service_name"].startswith("前门旅游专线")
    assert detail["gateway"].startswith("慕田峪长城")
    assert detail["depart_time"] == "14:30"
    assert lunch.next_leg_detail is None
    assert lunch.next_leg_mode is None
    # 锚离开班次点：档案清空，腿回打车模型
    plan.days[0].items.remove(lunch)
    plan.days[0].items.append(lunch)
    resolve_meal_anchors(plan)
    assert lunch.access_mode is None
    assert lunch.access_return_times is None


class _FakeProfileStore:
    """假档案源（poi_access.configure_profiles 的入参形状）。"""

    def __init__(self, profiles):
        self._profiles = profiles

    def access_profiles(self, cities=None):
        return dict(self._profiles)


def test_outbound_detail_fills_window_from_service_store():
    """卡上没有窗口字段（wish 快路径）时，去程明细从班次库补线名/乘车点/班次，
    不再只剩「乘车点」占位、专线行消失。"""
    from app.services import access_services

    access_services.configure_store(_FakeStore([_svc_row()]))
    try:
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
        )
        plan = ItineraryPlan(
            itinerary_id="x",
            cities=["北京"],
            days=[DayPlan(day=1, base_city="北京", items=[hotel, mt])],
            assumptions=[],
        )
        annotate_legs(plan)
        detail = hotel.next_leg_detail
        assert detail is not None and detail["mode"] == "access"
        assert detail["service_name"].startswith("前门旅游专线")
        assert detail["gateway"].startswith("前门大街北口")
        assert detail["alight"].startswith("慕田峪长城")
        assert "07:30" in detail["departures"]
        assert "14:30" in detail["returns"]
    finally:
        access_services.configure_store(None)


def test_return_chain_when_card_only_has_profile_archive():
    """wish 快路径不经过 attach_access：卡上只有 profile 档案（无窗口字段）
    时，锚定午餐卡继承档案、回城腿仍出三段——线名/返程班次按班次库补。"""
    from app.services import access_services, poi_access

    profile = {
        ("北京", "慕田峪长城"): dict(
            access_mode="shuttle",
            access_service_minutes=90,
            access_wait_minutes=10,
            access_last_mile_minutes=8,
            access_boarding_lon=116.3982,
            access_boarding_lat=39.8988,
        )
    }
    access_services.configure_store(_FakeStore([_svc_row()]))
    poi_access.configure_profiles(_FakeProfileStore(profile))
    poi_access._CITY_PROFILE_CACHE.clear()
    try:
        mt = _v(
            "mt",
            "慕田峪长城",
            116.5598,
            40.4267,
            start_time=time(11, 8),
            end_time=time(12, 38),
        )
        lunch = VisitItem(
            item_id="food-lunch-ph-d1",
            name="午饭（自由安排）",
            category="food",
            city="北京",
            day=1,
            duration_minutes=60,
            anchor_from_prev=True,
            start_time=time(12, 38),
            end_time=time(13, 38),
        )
        wfj = _v(
            "wfj",
            "王府井",
            116.4109,
            39.9097,
            start_time=time(15, 8),
            end_time=time(16, 38),
        )
        plan = ItineraryPlan(
            itinerary_id="x",
            cities=["北京"],
            days=[DayPlan(day=1, base_city="北京", items=[mt, lunch, wfj])],
            assumptions=[],
        )
        annotate_legs(plan)
        # 回城链挂回景区卡（占位餐卡不重复显示）
        detail = mt.next_leg_detail
        assert detail is not None and detail["direction"] == "return"
        assert detail["service_name"].startswith("前门旅游专线")
        assert detail["gateway"].startswith("慕田峪长城")
        assert detail["alight"].startswith("前门大街北口")
        assert detail["departures"] == ["14:30", "15:30", "16:30"]
        assert detail["depart_time"] == "14:30"
        assert mt.next_leg_mode == "access"
        assert lunch.next_leg_detail is None
    finally:
        access_services.configure_store(None)
        poi_access.configure_profiles(None)
        poi_access._CITY_PROFILE_CACHE.clear()


def test_morning_departure_anchor_back_calcs_hotel_start():
    """班次硬铆钉（2026-11-16 拍板）：默认取推荐块「08:30 起第一班」=08:30 班，
    回算离店 = 08:30 − 31（打车 16+早高峰 15）= 07:59（到站即发车、候车归零），
    首站 = 08:30 + 90 + 8 = 10:08 开场。
    """
    from app.services import access_services
    from app.services.itinerary import rules

    access_services.configure_store(_FakeStore([_svc_row()]))
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
        got = rules.morning_departure_anchor(
            mt, from_point=GeoPoint(lon=116.4074, lat=39.9042)
        )
    finally:
        access_services.configure_store(None)
    assert got is not None
    assert got["taxi_minutes"] == 31  # 16 打车 + 15′ 早高峰
    assert got["depart"] == 8 * 60 + 30  # 默认 = 08:30 起第一班
    assert got["hotel_start"] == 8 * 60 + 30 - 31  # 回算离店 07:59
    assert got["wait"] == 0  # 到站即发车
    assert got["first_start"] == 8 * 60 + 30 + 90 + 8  # 10:08 开场


def test_morning_anchor_requires_shuttle_timetable_and_real_boarding():
    """锚定只吃「班次接驳件 + 有时刻表」：普通景点/无时刻表返回 None（走旧窗口）。"""
    from app.services import access_services
    from app.services.itinerary import rules

    access_services.configure_store(None)
    plain = _v("p", "故宫", 116.397, 39.916)
    assert (
        rules.morning_departure_anchor(
            plain, from_point=GeoPoint(lon=116.4074, lat=39.9042)
        )
        is None
    )
    mt_no_tt = _v(
        "mt2",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_last_mile_minutes=8,
        access_depart_times=[],
        access_wait_minutes=10,
    )
    # 无 store、无卡上时刻表：不锚定（经验值兜底）
    assert (
        rules.morning_departure_anchor(
            mt_no_tt, from_point=GeoPoint(lon=116.4074, lat=39.9042)
        )
        is None
    )
    # 无打车起点（酒店/城心锚都缺）：不锚定
    assert rules.morning_departure_anchor(mt_no_tt, from_point=None) is None


def test_morning_rush_buffers_only_the_hotel_departure_taxi():
    """早高峰 15′ 只加晨卡出发的打车段；景间腿不重复加。"""
    from app.services.itinerary import rules

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
    site = _v("s", "前门大街", 116.3982, 39.8988)
    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_last_mile_minutes=8,
        access_depart_times=["07:30", "08:30", "09:30", "10:30"],
    )
    got = rules.access_breakdown(hotel, mt)
    assert got is not None and got["rush"] == 15
    got2 = rules.access_breakdown(site, mt)
    assert got2 is not None and got2["rush"] == 0


def test_attach_morning_card_anchors_to_nearest_departure():
    """attach 接锚定：默认 08:30 班 → 卡 07:59-08:29；首站「班次+车上+落客」
    10:08 开场（到站即发车）。"""
    from app.services import access_services
    from app.services.agent.hotel_stays import attach_hotel_mornings, is_hotel_morning

    access_services.configure_store(_FakeStore([_svc_row()]))
    try:
        night = VisitItem(
            item_id="hotel-night-d1",
            name="丽枫酒店",
            city="北京",
            day=1,
            category="hotel",
            duration_minutes=60,
            start_time=time(21, 30),
            end_time=time(22, 30),
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
        days = [DayPlan(day=1, base_city="北京", items=[night, mt])]
        attach_hotel_mornings(days)
        card = next(i for i in days[0].items if is_hotel_morning(i))
        assert (card.start_time, card.end_time) == (time(7, 59), time(8, 29))
        assert (mt.start_time, mt.end_time) == (time(10, 8), time(11, 8))
        # 幂等：再跑一遍（已有晨卡不重复插）
        assert attach_hotel_mornings(days) == []
        card2 = next(i for i in days[0].items if is_hotel_morning(i))
        assert (card2.start_time, card2.end_time) == (time(7, 59), time(8, 29))
    finally:
        access_services.configure_store(None)


def test_morning_anchor_honors_user_picked_departure():
    """点选班次优先（2026-11-16「班次可以点击选取重排」）：点 09:30 → 离店 08:59，
    首站 11:08；不再回默认的 08:30 班。"""
    from app.services import access_services
    from app.services.itinerary import rules

    access_services.configure_store(_FakeStore([_svc_row()]))
    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_last_mile_minutes=8,
        access_depart_times=["07:30", "08:30", "09:30", "10:30"],
    )
    try:
        got = rules.morning_departure_anchor(
            mt,
            from_point=GeoPoint(lon=116.4074, lat=39.9042),
            chosen="09:30",
        )
    finally:
        access_services.configure_store(None)
    assert got is not None
    assert got["depart"] == 9 * 60 + 30
    assert got["hotel_start"] == 9 * 60 + 30 - 31  # 08:59
    assert got["first_start"] == 9 * 60 + 30 + 90 + 8  # 11:08


def test_return_leg_honors_user_picked_return():
    """点选返程优先：卡上 access_chosen_return=15:30，回城腿就按 15:30 发车。"""
    from app.services.itinerary import rules

    mt = _v(
        "mt",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=90,
        access_last_mile_minutes=8,
        access_return_times=["14:30", "15:30", "16:30"],
        access_chosen_return="15:30",
        end_time=time(14, 8),
    )
    nxt = _v("nx", "提督餐厅", 116.42, 39.92)
    br = rules.access_breakdown(mt, nxt)
    assert br is not None and br["direction"] == "return"
    assert br["depart"] == 15 * 60 + 30
    # board = 14:08 + 走回乘车点 8 分 = 14:16 → 候车 74 分钟
    assert br["wait"] == 15 * 60 + 30 - (14 * 60 + 8 + 8)


def test_taxi_leg_shows_on_anchored_lunch_card():
    """2026-11-17 用户口径：朱家角 → 静安寺的车发生在午饭之后。

    「距离下一站应该放在午饭后，而不是朱家角」——腿挂在锚在本站的午饭卡
    （餐后出发），景区卡不再背这条腿；回城仍由回城链/独立回城卡负责。
    """
    zjj = VisitItem(
        item_id="v11",
        name="朱家角古镇",
        category="attraction",
        city="上海",
        day=1,
        location=GeoPoint(lon=121.05052418499841, lat=31.11416165422822),
        start_time=time(11, 29),
        end_time=time(12, 59),
        duration_minutes=90,
    )
    lunch = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        category="food",
        city="上海",
        day=1,
        anchor_from_prev=True,
        start_time=time(14, 29),
        end_time=time(15, 29),
        duration_minutes=60,
    )
    jingan = VisitItem(
        item_id="v7",
        name="静安寺",
        category="attraction",
        city="上海",
        day=1,
        location=GeoPoint(lon=121.4453, lat=31.2231),
        start_time=time(15, 53),
        end_time=time(17, 23),
        duration_minutes=90,
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=[zjj, lunch, jingan])],
        assumptions=[],
    )
    annotate_legs(plan)
    assert lunch.anchor_location is not None  # 地址仍继承景区
    # 腿挂在午饭卡（餐后出发去静安寺）
    assert lunch.distance_to_next_km and lunch.distance_to_next_km > 30
    assert lunch.next_leg_mode == "taxi"
    assert lunch.next_leg_minutes and lunch.next_leg_minutes > 30
    # 景区卡不再背这条腿
    assert zjj.distance_to_next_km is None
    assert zjj.next_leg_minutes is None


# ------------------------------------------- R13m 引擎去程卡班次显示链


def _engine_remote_day_items():
    from datetime import time as dtime

    mt = _v(
        "v1",
        "慕田峪长城",
        116.5598,
        40.4267,
        start_time=dtime(10, 8),
        end_time=dtime(13, 28),
        duration_minutes=200,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_minutes=98,  # 引擎盖卡口径：ride+last_mile
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
    lunch = VisitItem(
        item_id="meal-lunch-1",
        name="午餐",
        category="food",
        city="北京",
        day=1,
        start_time=dtime(13, 28),
        end_time=dtime(14, 28),
        duration_minutes=60,
        anchor_location=GeoPoint(lon=116.5598, lat=40.4267),
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
    # 锚在景区的占位晚餐（真实引擎日形状：回城卡在场 + 晚餐同址——
    # 没有城内下一站，_attach_tail_return 按同址档位挂返程链）。
    dinner = VisitItem(
        item_id="meal-dinner-1",
        name="晚饭",
        category="food",
        city="北京",
        day=1,
        start_time=dtime(17, 0),
        end_time=dtime(18, 30),
        duration_minutes=90,
        anchor_from_prev=True,
    )
    return [out, mt, lunch, ret, dinner], out, mt, lunch


def test_engine_outbound_card_gets_chips_and_no_bogus_taxi_tail():
    """R13m：引擎远郊日——去程卡挂班次 chips 数据；景区卡挂班车回城链；
    同址午餐卡不再被误挂「打车回城」假块（回城卡在场时尾部打车闸关闭）。
    """
    items, out, mt, lunch = _engine_remote_day_items()
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=items)],
        assumptions=[],
    )
    annotate_legs(plan)
    # 去程卡：班次显示链（chips 数据）
    d = out.next_leg_detail or {}
    assert out.next_leg_mode == "access"
    assert d["service_name"] == "前门旅游专线"
    assert d["departures"] == ["07:30", "08:30", "09:30", "10:30"]
    assert d["returns"] == ["14:30", "15:30", "16:30"]
    assert d["depart_time"] == "08:30"
    assert d["owner_item_id"] == "access-out-v1"
    assert d["next_item_id"] == "v1"
    # 景区卡：班车回城链（_attach_tail_return 逐档取「仍有返程班的
    # 最后一档」= 午餐散场 13:28 + 走回 8 → 首班 14:30）
    m = mt.next_leg_detail or {}
    assert m["direction"] == "return"
    assert m["service_name"] == "前门旅游专线"
    assert m["departures"] == ["14:30", "15:30", "16:30"]
    # 逐档取「仍有返程班的最后一档」：午餐散场 14:28 + 走回 8 = 14:36
    # → 下一班 15:30（不是按景区散场 13:36 的 14:30）。
    assert m["depart_time"] == "15:30"
    # 同址午餐卡：无打车回城假块（R13m 尾部打车闸被回城卡挡住）
    assert lunch.next_leg_detail is None
    assert lunch.next_leg_mode is None


def test_engine_placeholder_dinner_anchors_to_city_stop():
    """R13m：引擎占位晚餐 id（meal-dinner-<day>）也走「散场后跟下一站吃」
    锚定——此前 food-dinner-ph* 字面前缀认不出引擎 id，晚饭错锚远郊点。
    """
    from app.services.itinerary.legs import resolve_meal_anchors

    items, _out, mt, _lunch = _engine_remote_day_items()
    night = VisitItem(
        item_id="hotel-night-d1",
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="北京",
        day=1,
        start_time=time(21, 0),
        end_time=time(22, 0),
        duration_minutes=60,
        soft_pin=True,
        location=GeoPoint(lon=116.4074, lat=39.9042),
    )
    dinner = VisitItem(
        item_id="meal-dinner-1",
        name="晚饭",
        category="food",
        city="北京",
        day=1,
        start_time=time(17, 30),
        end_time=time(18, 30),
        duration_minutes=60,
        anchor_from_prev=True,
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[mt, dinner, night])],
        assumptions=[],
    )
    resolve_meal_anchors(plan)
    d = next(i for i in plan.days[0].items if i.item_id == "meal-dinner-1")
    assert d.anchor_location is not None
    assert d.anchor_location.lon == 116.4074  # 跟下一站（酒店）吃
    assert (d.access_mode or None) is None  # 不再继承远郊点档案


# ------------------------------------------- R13o⑨ 同址嵌套宿主收尾


def test_plain_tail_return_waits_for_same_venue_host_end():
    """R13o⑨：同址嵌套餐（F-22）下回城段从宿主散场起算——798 游到
    20:16 时回城不得从晚饭 19:28 起算。"""
    from datetime import time as dtime

    host = _v(
        "host798",
        "798艺术区",
        116.5847,
        39.9842,
        start_time=dtime(16, 46),
        end_time=dtime(20, 16),
        duration_minutes=210,
    )
    dinner = VisitItem(
        item_id="meal-dinner-2",
        name="晚饭",
        category="food",
        city="北京",
        day=1,
        start_time=dtime(17, 58),
        end_time=dtime(19, 28),
        duration_minutes=90,
        anchor_location=GeoPoint(lon=116.5847, lat=39.9842),
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[host, dinner])],
        assumptions=[],
    )
    annotate_legs(plan)
    d = dinner.next_leg_detail or {}
    assert d.get("direction") == "return"
    assert d.get("depart_time") is None or d["depart_time"] >= "20:16"
    assert d.get("board_time") >= "20:16"
