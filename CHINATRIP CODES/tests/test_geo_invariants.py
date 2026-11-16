# -*- coding: utf-8 -*-
"""地理不变式（聚族→定天→日内）2026-11-16：去重选真身 + 补点后清异簇。"""

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


def _plan(items, days=2):
    return ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[
            DayPlan(
                day=n,
                base_city="上海",
                items=[i for i in items if i.day == n],
            )
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


def test_fill_then_invariant_leaves_no_far_outlier():
    """补点把远件塞进簇日 → 补点收尾跑不变式后不得留在该日（上海 D1 案）。"""
    a = _v("a", "上海中心大厦", 121.505, 31.235, day=1, start=time(9, 0))
    b = _v("b", "黄浦江游览（东方明珠码头）", 121.500, 31.240, day=1, start=time(11, 0))
    plan = _plan([a, b])
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
    _fill_leftover_with_diverse_sights(plan, bench=bench)
    _apply_geo_invariants(plan)
    assert "朱家角大清邮局" not in _day_names(plan, 1)
