# -*- coding: utf-8 -*-
"""地理不变式（聚族→定天→日内）2026-11-16：去重/簇日/族亲和/晨卡下限。"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import (
    _apply_geo_invariants,
    _dedupe_visit_keepers,
    _fill_leftover_with_diverse_sights,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    UnplacedCandidate,
    VisitItem,
)


def _v(item_id, name, lon, lat, *, day=1, cat="sight", start=None, pinned=False):
    return VisitItem(
        item_id=item_id,
        name=name,
        city="上海",
        day=day,
        category=cat,
        duration_minutes=90,
        location=GeoPoint(lon=lon, lat=lat),
        start_time=start,
        end_time=time(start.hour + 1, start.minute) if start else None,
        pinned=pinned,
    )


def _morning(day=1, start=time(10, 30)):
    return VisitItem(
        item_id=f"hotel-morning-d{day}",
        name="出发",
        city="上海",
        day=day,
        category="hotel",
        duration_minutes=0,
        start_time=start,
        end_time=start,
    )


def _plan(items, days=2):
    return ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[
            DayPlan(day=n, base_city="上海", items=[i for i in items if i.day == n])
            for n in range(1, days + 1)
        ],
    )


def _day_names(plan, day):
    return [i.name for i in plan.days[day - 1].items if isinstance(i, VisitItem)]


def test_dedupe_keeps_the_twin_with_coordinates():
    """同站孪生：无坐标的钉住卡不得压过有坐标的真身（朱家角案）。"""
    no_loc = VisitItem(
        item_id="a",
        name="朱家角镇",
        city="上海",
        day=2,
        category="sight",
        duration_minutes=180,
        pinned=True,
    )
    good = _v("b", "朱家角古镇", 121.05, 31.114, day=2)
    keepers, dropped = _dedupe_visit_keepers([no_loc, good])
    assert len(keepers) == 1
    assert keepers[0].name == "朱家角古镇"
    assert keepers[0].location is not None
    assert dropped == ["朱家角镇"]


def test_geo_invariant_evicts_far_item_from_cluster_day():
    """陆家嘴簇日塞进 40km 外的件：不变式必须把它清出该日。"""
    a = _v("a", "上海中心大厦", 121.505, 31.235, day=1, start=time(9, 0))
    b = _v("b", "黄浦江游览（东方明珠码头）", 121.500, 31.240, day=1, start=time(11, 0))
    far = _v("c", "朱家角大清邮局", 121.065, 31.111, day=1, start=time(14, 0))
    plan = _plan([a, b, far])
    _apply_geo_invariants(plan)
    assert "朱家角大清邮局" not in _day_names(plan, 1)


def test_pinned_only_card_moves_and_lands_after_departure_card():
    """非必去钉住件可被聚族挪走，且挪后不得早于当天晨卡（上海 D2 案）。"""
    morning = _morning(day=2, start=time(10, 30))
    a = _v("a", "上海博物馆", 121.475, 31.230, day=2, start=time(9, 0))
    b = _v("b", "豫园", 121.492, 31.227, day=2, start=time(13, 0))
    c = _v("c", "外滩", 121.490, 31.240, day=2, start=time(17, 0))
    far = _v("d", "朱家角镇", 121.046, 31.103, day=2, start=time(15, 0), pinned=True)
    plan = _plan([morning, a, b, c, far])
    _apply_geo_invariants(plan, relax_pins=True)
    assert "朱家角镇" not in _day_names(plan, 2)
    moved = [
        i for d in plan.days for i in d.items if getattr(i, "name", "") == "朱家角镇"
    ]
    assert moved
    if moved[0].start_time is not None:
        assert moved[0].start_time >= time(8, 30)


def test_fill_keeps_new_card_inside_the_days_cluster():
    """补点族亲和：当天已有陆家嘴件，40km 外的候选不得补进来。"""
    a = _v("a", "上海中心大厦", 121.505, 31.235, day=1, start=time(9, 0))
    plan = _plan([a], days=1)
    bench = [
        UnplacedCandidate(
            name="朱家角大清邮局",
            category="sight",
            duration_minutes=60,
            location=GeoPoint(lon=121.065, lat=31.111),
            city="上海",
            poi_id="far",
        )
    ]
    assert _fill_leftover_with_diverse_sights(plan, bench=bench) == []


def test_fill_skips_same_place_core_duplicate():
    """同地内核：已有「朱家角镇」，不再补「朱家角古镇」。"""
    a = _v("a", "朱家角镇", 121.046, 31.103, day=1, start=time(9, 0))
    plan = _plan([a])
    bench = [
        UnplacedCandidate(
            name="朱家角古镇",
            category="sight",
            duration_minutes=180,
            location=GeoPoint(lon=121.050, lat=31.114),
            city="上海",
            poi_id="dup",
        )
    ]
    assert _fill_leftover_with_diverse_sights(plan, bench=bench) == []
