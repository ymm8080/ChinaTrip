# -*- coding: utf-8 -*-
"""白天晚闸出站闸 + 开放形态豁免（2026-11-17 拍板「晚闸是 16:30，适用于
有明确开放时间的封闭景点；M50/武康路类商业街 citywalk 不是封闭景区没有
开放时间，晚闸豁免」）。"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import _evict_evening_gate_breachers
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)


def _v(item_id, name, start, end, *, cat="sight", lon=121.47, lat=31.23, **kw):
    dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return VisitItem(
        item_id=item_id,
        name=name,
        city="上海",
        day=1,
        category=cat,
        duration_minutes=kw.pop("dur", dur),
        location=GeoPoint(lon=lon, lat=lat),
        start_time=start,
        end_time=end,
        **kw,
    )


def _plan(items):
    return ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=items)],
        assumptions=[],
    )


def test_open_form_no_hours_kept_m50_case():
    """M50创意园：商业街/创意园无营业窗 → 开放形态，16:58 照排（拍板案）。"""
    plan = _plan([_v("m50", "M50创意园", time(16, 58), time(19, 28), cat="citywalk")])
    assert _evict_evening_gate_breachers(plan) == []
    assert plan.days[0].items[0].name == "M50创意园"


def test_open_form_allday_hours_kept_xintiandi_case():
    """新天地/田子坊类 00:00-24:00 全天窗 → 不设限，不吃晚闸。"""
    plan = _plan(
        [
            _v(
                "xtd",
                "新天地",
                time(16, 58),
                time(19, 28),
                cat="attraction",
                opening_hours="周一至周日 00:00-24:00",
            )
        ]
    )
    assert _evict_evening_gate_breachers(plan) == []


def test_enclosed_big_site_past_band_evicted_jingan_case():
    """静安寺 07:30-18:00 受限窗+90min 大点：16:15 > 15:30 带 → 移出转想排。"""
    plan = _plan(
        [
            _v(
                "jas",
                "静安寺",
                time(16, 15),
                time(17, 45),
                cat="attraction",
                poi_id="jas",
                opening_hours="周一至周日 07:30-18:00",
            ),
            _v("d", "晚饭（自由安排）", time(19, 30), time(21, 0), cat="food"),
        ]
    )
    notes = _evict_evening_gate_breachers(plan)
    assert notes and "静安寺" in notes[0] and "15:30" in notes[0]
    assert [i.name for i in plan.days[0].items] == ["晚饭（自由安排）"]
    u = plan.unplaced[0]
    assert u.name == "静安寺"
    assert u.reason == "evening_gate"
    assert u.day_hint == 1


def test_enclosed_generic_cap_1630_boundary():
    """受限窗 60min 普通件：16:20 合法（新 16:30 带）、16:40 越闸清退。"""
    ok = _plan(
        [
            _v(
                "a",
                "小馆",
                time(16, 20),
                time(17, 20),
                cat="museum",
                poi_id="mus",
                opening_hours="周二至周日 09:00-18:00",
            )
        ]
    )
    assert _evict_evening_gate_breachers(ok) == []
    breach = _plan(
        [
            _v(
                "b",
                "小馆",
                time(16, 40),
                time(17, 40),
                cat="museum",
                poi_id="mus",
                opening_hours="周二至周日 09:00-18:00",
            )
        ]
    )
    notes = _evict_evening_gate_breachers(breach)
    assert notes and "16:30" in notes[0]


def test_straddle_and_pinned_kept():
    """骑窗（开场在闸前）合法；pinned+有时刻=铁律19 用户确认时刻不拦。"""
    plan = _plan(
        [
            _v(
                "y",
                "豫园",
                time(15, 15),
                time(16, 30),
                cat="park",
                opening_hours="周二至周日 09:00-16:30(16:00停止入馆)",
            ),
            _v(
                "p",
                "用户钉的静安寺",
                time(17, 0),
                time(18, 30),
                cat="attraction",
                pinned=True,
            ),
        ]
    )
    assert _evict_evening_gate_breachers(plan) == []
    assert len(plan.days[0].items) == 2


def test_evening_bvt_and_food_hotel_kept():
    plan = _plan(
        [
            _v(
                "c",
                "黄浦江游览",
                time(19, 15),
                time(21, 15),
                cat="theme_park",
                best_visit_time="evening",
            ),
            _v("d", "晚饭（自由安排）", time(17, 45), time(19, 15), cat="food"),
            _v("h", "回酒店", time(21, 8), time(22, 8), cat="hotel"),
        ]
    )
    assert _evict_evening_gate_breachers(plan) == []
    assert len(plan.days[0].items) == 3


def test_idempotent_second_run_clean():
    plan = _plan(
        [
            _v(
                "jas",
                "静安寺",
                time(16, 15),
                time(17, 45),
                cat="attraction",
                poi_id="jas",
                opening_hours="周一至周日 07:30-18:00",
            )
        ]
    )
    assert _evict_evening_gate_breachers(plan)
    assert _evict_evening_gate_breachers(plan) == []
    assert len(plan.unplaced) == 1
