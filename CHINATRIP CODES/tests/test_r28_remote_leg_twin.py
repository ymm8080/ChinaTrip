# -*- coding: utf-8 -*-
"""R28(2026-11-23)远郊腿消失三刀回归。

用户实报:「八达岭慕田峪长城旅游区 远郊腿消失了」(会话 97c29c4d,
day3 v8 卡 poi_id=5a_004,access_* 全空、next_leg_mode=taxi 91 分钟)。

根因链:
1. 选点并卡:_same_site 名字互含无坐标门——合名行(坐标在延庆八达岭侧)
   把 50km 外、有官方班次档案的原生「慕田峪长城」卡并掉(腿换宿主)。
2. 装配挂腿:attach_access 按卡名精确查档案——合名卡自己的档案是 bus
   估算(不在 train/shuttle/ferry 白名单)、班次库无合名官方行
   (STRICT_OFFICIAL)、班次窗按名查落空,三闸全拦(腿蒸发)。
3. 引擎绑定:live._access_profiles_for 互含命中随池序——「慕田峪长城」
   班次行可能错绑合名行(50km 错档档案)。

修:①并卡名字互含通道补 30km 地理闸(_twin_site_gate);②attach_access
沿 POI 本体坐标继承 10km 内最近合格档案(_nearby_official_profile);
③班次行优先绑精确同名池行。
"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.poi_access import attach_access

# --- 坐标(实库方位)------------------------------------------------------------
#: 合名行「八达岭慕田峪长城旅游区」5a_004:坐标在延庆八达岭侧。
LON_HEMING, LAT_HEMING = 115.9780, 40.3620
#: 八达岭长城 ct_北京_2:与合名行同景区,直线约 3km。
LON_BADALING, LAT_BADALING = 116.0243, 40.3597
#: 慕田峪长城 ct_北京_8:怀柔侧,与合名行直线约 50km(非同站)。
LON_MUTIANYU, LAT_MUTIANYU = 116.5598, 40.4267

NAME_HEMING = "八达岭慕田峪长城旅游区"
NAME_BADALING = "八达岭长城"
NAME_MUTIANYU = "慕田峪长城"


def _twin_gate(row_a, row_b):
    from app.services.agent.plan import _twin_site_gate

    return _twin_site_gate(row_a, row_b)


def test_twin_site_gate_rejects_far_pairs():
    """八达岭/慕田峪相距约 50km:合名行与慕田峪行不是同站,不并。"""
    heming = {"name": NAME_HEMING, "location": {"lon": LON_HEMING, "lat": LAT_HEMING}}
    mutianyu = {
        "name": NAME_MUTIANYU,
        "location": {"lon": LON_MUTIANYU, "lat": LAT_MUTIANYU},
    }
    badaling = {
        "name": NAME_BADALING,
        "location": {"lon": LON_BADALING, "lat": LAT_BADALING},
    }
    assert _twin_gate(heming, mutianyu) is False
    # 同景区 3km 内的互含对(合名行 vs 八达岭行)保持可并。
    assert _twin_gate(heming, badaling) is True


def test_twin_site_gate_keeps_legacy_behaviour_without_coords():
    """缺坐标保持既有池级行为(不因坐标缺失而新拦)。"""
    a = {"name": NAME_HEMING, "location": None}
    b = {"name": NAME_MUTIANYU, "location": {"lon": LON_MUTIANYU, "lat": LAT_MUTIANYU}}
    c = {"name": NAME_MUTIANYU, "location": None}
    assert _twin_gate(a, b) is True
    assert _twin_gate(c, b) is True
    assert _twin_gate(c, c) is True


# --- attach_access 近邻档案回退 ------------------------------------------------


def _svc_row(**kw):
    row = dict(
        city="北京",
        poi_name=NAME_MUTIANYU,
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
        ticket_url=None,
        last_mile_minutes=8,
        note=None,
        note_en=None,
        source="official:mutianyugreatwall",
        source_url=None,
        official_url=None,
        official_status="verified",
        window_source="official",
        fare_source="official",
    )
    row.update(kw)
    return row


class _FakeStore:
    """假班次源(access_services.configure_store 的入参形状)。"""

    def __init__(self, rows):
        self._rows = rows

    def access_services(self, cities=None):
        return list(self._rows)


def _profile(**kw):
    prof = dict(
        access_mode="shuttle",
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_boarding_lon=116.3982,
        access_boarding_lat=39.8988,
        poi_lon=None,
        poi_lat=None,
    )
    prof.update(kw)
    return prof


def _heming_plan():
    card = VisitItem(
        item_id="v8",
        name=NAME_HEMING,
        poi_id="5a_004",
        city="北京",
        day=3,
        category="sight",
        duration_minutes=240,
        location=GeoPoint(lon=LON_HEMING, lat=LAT_HEMING),
        start_time=time(9, 0),
        end_time=time(13, 0),
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=3, base_city="北京", items=[card])],
        assumptions=[],
    )
    return plan, card


def test_attach_falls_back_to_nearby_member_profile():
    """合名卡:自己的档案是 bus 估算(闸拦),班次库无合名官方行 →
    沿 POI 坐标继承 10km 内八达岭合格档案,窗按档案 POI 名挂。"""
    from app.services import access_services

    profiles = {
        ("北京", NAME_HEMING): _profile(
            access_mode="bus",
            access_service_minutes=136,
            access_boarding_lon=None,
            access_boarding_lat=None,
            poi_lon=LON_HEMING,
            poi_lat=LAT_HEMING,
        ),
        ("北京", NAME_BADALING): _profile(
            access_service_minutes=122,
            poi_lon=LON_BADALING,
            poi_lat=LAT_BADALING,
        ),
        ("北京", NAME_MUTIANYU): _profile(
            poi_lon=LON_MUTIANYU,
            poi_lat=LAT_MUTIANYU,
        ),
    }
    access_services.configure_store(
        _FakeStore(
            [
                _svc_row(
                    poi_name=NAME_BADALING,
                    source="official:badaling",
                    ride_minutes=100,
                    outbound_times=["07:00", "08:00"],
                    return_times=["15:00", "16:00"],
                )
            ]
        )
    )
    try:
        plan, card = _heming_plan()
        filled = attach_access(plan, profiles)
        assert filled == 1
        assert card.access_mode == "shuttle"
        assert card.access_boarding == GeoPoint(lon=116.3982, lat=39.8988)
        # 窗按档案 POI 名(八达岭长城)查班次库——合名查永远落空;
        # 车上分钟随窗覆盖为班次行真值(100,非档案估算 122/90)。
        assert card.access_depart_times == ["07:00", "08:00"]
        assert card.access_return_times == ["15:00", "16:00"]
        assert card.access_service_minutes == 100
    finally:
        access_services.configure_store(None)


def test_attach_keeps_taxi_when_no_nearby_profile():
    """近邻只有 50km 外的慕田峪档:绝不挂错档班次,维持打车链。"""
    from app.services import access_services

    profiles = {
        ("北京", NAME_HEMING): _profile(
            access_mode="bus",
            access_boarding_lon=None,
            access_boarding_lat=None,
            poi_lon=LON_HEMING,
            poi_lat=LAT_HEMING,
        ),
        ("北京", NAME_MUTIANYU): _profile(
            poi_lon=LON_MUTIANYU,
            poi_lat=LAT_MUTIANYU,
        ),
    }
    access_services.configure_store(_FakeStore([_svc_row()]))
    try:
        plan, card = _heming_plan()
        filled = attach_access(plan, profiles)
        assert filled == 0
        assert card.access_mode is None
    finally:
        access_services.configure_store(None)


def test_attach_prefers_exact_profile_over_nearby():
    """原生卡:精确档案合格 → 不触发近邻回退(be8e2387 健康对照不回归)。"""
    from app.services import access_services

    profiles = {
        ("北京", NAME_MUTIANYU): _profile(
            access_service_minutes=90,
            poi_lon=LON_MUTIANYU,
            poi_lat=LAT_MUTIANYU,
        ),
        ("北京", NAME_BADALING): _profile(
            access_service_minutes=122,
            poi_lon=LON_BADALING,
            poi_lat=LAT_BADALING,
        ),
    }
    access_services.configure_store(_FakeStore([_svc_row()]))
    try:
        plan = ItineraryPlan(
            itinerary_id="x",
            cities=["北京"],
            days=[
                DayPlan(
                    day=1,
                    base_city="北京",
                    items=[
                        VisitItem(
                            item_id="mt",
                            name=NAME_MUTIANYU,
                            poi_id="ct_北京_8",
                            city="北京",
                            day=1,
                            category="sight",
                            duration_minutes=240,
                            location=GeoPoint(lon=LON_MUTIANYU, lat=LAT_MUTIANYU),
                            start_time=time(9, 0),
                            end_time=time(13, 0),
                        )
                    ],
                )
            ],
            assumptions=[],
        )
        filled = attach_access(plan, profiles)
        assert filled == 1
        card = plan.days[0].items[0]
        assert card.access_mode == "shuttle"
        assert card.access_service_minutes == 90  # 慕田峪档,非八达岭档(122)
    finally:
        access_services.configure_store(None)


# --- live._access_profiles_for 精确优先绑定 ------------------------------------


def test_live_binds_service_row_to_exact_pool_name_first():
    """池里同时有精确行与互含合名行:慕田峪班次行必绑精确行。"""
    from app.services.trip_solver.live import _access_profiles_for

    pool = [
        {"name": NAME_HEMING, "id": "5a_004"},
        {"name": NAME_MUTIANYU, "id": "ct_北京_8"},
    ]
    rows = [_svc_row(poi_name=NAME_MUTIANYU, ride_minutes=144)]
    out = _access_profiles_for(pool, rows)
    assert len(out) == 1
    assert out[0].to_poi == "ct_北京_8"


def test_live_containment_binding_still_works_without_exact_row():
    """池里只有合名行(别名/简称形态):互含回退照旧成立。"""
    from app.services.trip_solver.live import _access_profiles_for

    pool = [{"name": NAME_HEMING, "id": "5a_004"}]
    rows = [_svc_row(poi_name=NAME_MUTIANYU, ride_minutes=144)]
    out = _access_profiles_for(pool, rows)
    assert len(out) == 1
    assert out[0].to_poi == "5a_004"
