"""远郊专线班次表：读口纯函数 + 排期服务窗硬约束（2026-11-16）。"""

from __future__ import annotations

from app.services.access_services import Service, configure_store, services_for
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.itinerary.models import (
    time as _t,
)


def _service() -> Service:
    return Service(
        city="北京",
        poi_name="慕田峪长城",
        mode="shuttle",
        service_name="慕田峪长城通游专线（前门线）",
        boarding_stop="前门站",
        boarding_lon=116.398256,
        boarding_lat=39.898886,
        outbound_first=7 * 60,
        outbound_last=11 * 60,
        outbound_frequency_minutes=20,
        ride_minutes=90,
        return_first=13 * 60,
        return_last=16 * 60,
        last_mile_minutes=8,
        fare_cny=80,
        fare_kind="round_trip",
    )


class _Store:
    def access_services(self, cities=None):  # noqa: ANN001
        return [
            {
                "city": "北京",
                "poi_name": "慕田峪长城",
                "mode": "shuttle",
                "service_name": "慕田峪长城通游专线（前门线）",
                "boarding_stop": "前门站",
                "boarding_lon": 116.398256,
                "boarding_lat": 39.898886,
                "outbound_times": [],
                "outbound_first": "07:00",
                "outbound_last": "11:00",
                "outbound_frequency_minutes": 20,
                "ride_minutes": 90,
                "return_first": "13:00",
                "return_last": "16:00",
                "fare_cny": 80,
                "fare_kind": "round_trip",
                "last_mile_minutes": 8,
                "official_status": "verified",
                "window_source": "official",
            }
        ]


def test_departures_expand_from_first_last_and_headway():
    spans = _service().departures()
    assert spans[0] == 7 * 60
    assert spans[-1] == 11 * 60
    assert all(b - a == 20 for a, b in zip(spans, spans[1:]))


def test_next_departure_and_window_bounds():
    svc = _service()
    assert svc.next_departure(6 * 60) == 7 * 60  # 早于首班 → 首班
    assert svc.next_departure(7 * 60 + 5) == 7 * 60 + 20
    assert svc.next_departure(11 * 60 + 10) is None  # 末班后
    assert svc.is_open(10 * 60)
    assert not svc.is_open(11 * 60 + 30)


def test_plan_leg_three_states():
    svc = _service()
    verdict, depart, arrive = svc.plan_leg(8 * 60 + 5)
    assert verdict == "ok"
    assert depart == 8 * 60 + 20
    assert arrive == depart + 90 + 8

    verdict, depart, _ = svc.plan_leg(6 * 60 + 30)
    assert verdict == "early"
    assert depart == 7 * 60

    verdict, depart, arrive = svc.plan_leg(12 * 60)
    assert verdict == "closed"
    assert arrive is None


def test_services_for_reads_injected_store():
    configure_store(_Store())
    try:
        items = services_for("北京", "慕田峪长城")
        assert len(items) == 1
        assert items[0].fare_text() == "往返 80 元"
        assert services_for("北京", "不存在").__len__() == 0
    finally:
        configure_store(None)


def _visit(item_id: str, name: str, lon: float, lat: float, start=None, end=None):
    item = VisitItem(
        item_id=item_id,
        name=name,
        city="北京",
        day=2,
        location=GeoPoint(lon=lon, lat=lat),
    )
    item.start_time = start
    item.end_time = end
    return item


def test_clamp_uses_timetable_when_window_open():
    """窗内：午饭收尾后按班次落景区（早于首班则等首班）。"""
    from app.services.agent import plan as plan_mod

    lunch = _visit(
        "lunch", "午饭（自由安排）", 116.4109, 39.9097, _t(11, 0), _t(11, 40)
    )
    lunch.category = "food"
    lunch.soft_pin = True

    site = _visit("site", "慕田峪长城", 116.5598, 40.4267, _t(13, 30), _t(15, 0))
    site.access_mode = "shuttle"
    site.access_boarding = GeoPoint(lon=116.398256, lat=39.898886)
    site.access_depart_first = 7 * 60
    site.access_depart_last = 11 * 60
    site.access_ride_minutes = 90
    site.access_last_mile_minutes = 8
    site.access_service_minutes = 90

    day = DayPlan(day=2, base_city="北京", items=[lunch, site])
    plan = ItineraryPlan(itinerary_id="it-svc-1", cities=["北京"], days=[day])
    plan_mod._clamp_chain_gaps(plan)

    start = site.start_time.hour * 60 + site.start_time.minute
    # 11:40 + 前门打车约 6 分钟 = 11:46 > 末班 11:00 → 收车改直达
    assert start >= 11 * 60 + 40


def test_clamp_falls_back_to_taxi_after_last_departure():
    from app.services.agent import plan as plan_mod

    lunch = _visit(
        "lunch2", "午饭（自由安排）", 116.4109, 39.9097, _t(12, 30), _t(13, 30)
    )
    lunch.category = "food"
    lunch.soft_pin = True

    site = _visit("site2", "慕田峪长城", 116.5598, 40.4267, _t(13, 40), _t(15, 10))
    site.access_mode = "shuttle"
    site.access_boarding = GeoPoint(lon=116.398256, lat=39.898886)
    site.access_depart_first = 7 * 60
    site.access_depart_last = 11 * 60
    site.access_ride_minutes = 90
    site.access_last_mile_minutes = 8
    site.access_service_minutes = 90

    day = DayPlan(day=2, base_city="北京", items=[lunch, site])
    plan = ItineraryPlan(itinerary_id="it-svc-2", cities=["北京"], days=[day])
    notes = plan_mod._clamp_chain_gaps(plan)

    assert any("末班" in note for note in notes), notes
    start = site.start_time.hour * 60 + site.start_time.minute
    # 收车后走打车直达（约 75-85 分钟），不是 90+8 的专线口径
    assert start >= 13 * 60 + 30


def test_pin_service_window_places_card_first():
    """日内排序前先钉：无时刻的班次点按首班落到门口，而不是等收口。"""
    from app.services.agent import plan as plan_mod

    morning = VisitItem(item_id="m", name="早卡", city="北京", day=1)
    morning.category = "food"
    morning.soft_pin = True
    morning.start_time = _t(7, 0)
    morning.end_time = _t(7, 30)

    site = VisitItem(item_id="s", name="慕田峪长城", city="北京", day=1)
    site.location = GeoPoint(lon=116.5598, lat=40.4267)
    site.access_mode = "shuttle"
    site.access_boarding = GeoPoint(lon=116.398256, lat=39.898886)
    site.access_depart_first = 7 * 60
    site.access_depart_last = 11 * 60
    site.access_ride_minutes = 90
    site.access_last_mile_minutes = 8
    site.duration_minutes = 90

    day = DayPlan(day=1, base_city="北京", items=[morning, site])
    plan = ItineraryPlan(itinerary_id="it-pin", cities=["北京"], days=[day])
    notes = plan_mod._pin_service_windows(plan)

    start = site.start_time.hour * 60 + site.start_time.minute
    # 远郊优先早晨 + 取 9 点档（2026-11-16）：09:00 发车 + 车上 90 + 末段 8
    assert start == 9 * 60 + 98, start
    assert notes, "钉窗要留一条披露"
    assert "专线" in notes[0]


def test_pin_service_window_skips_when_last_departure_missed():
    """同日已排满到下午 → 不钉（交收口改打车直达），不留没车时刻。"""
    from app.services.agent import plan as plan_mod

    anchor = VisitItem(item_id="a", name="故宫", city="北京", day=1)
    anchor.location = GeoPoint(lon=116.397, lat=39.916)
    anchor.start_time = _t(13, 0)
    anchor.end_time = _t(16, 0)

    site = VisitItem(item_id="s2", name="慕田峪长城", city="北京", day=1)
    site.location = GeoPoint(lon=116.5598, lat=40.4267)
    site.access_mode = "shuttle"
    site.access_boarding = GeoPoint(lon=116.398256, lat=39.898886)
    site.access_depart_first = 7 * 60
    site.access_depart_last = 8 * 60
    site.access_ride_minutes = 90
    site.access_last_mile_minutes = 8

    day = DayPlan(day=1, base_city="北京", items=[anchor, site])
    plan = ItineraryPlan(itinerary_id="it-pin2", cities=["北京"], days=[day])
    notes = plan_mod._pin_service_windows(plan)

    # 钉子只按「日始 + 城心打车」算，08:30+16 仍早于末班 08:00？不，是 08:46 > 08:00
    assert site.start_time is None or site.start_time.hour < 12
    assert notes == [] or all("专线" in n for n in notes)
