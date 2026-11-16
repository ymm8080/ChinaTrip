# -*- coding: utf-8 -*-
"""空档补点（收尾第③步）2026-11-16 上海案：下限/餐窗/重日短件/上限/幂等。"""

from __future__ import annotations

import asyncio
from datetime import time

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    _fill_leftover_with_diverse_sights,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    UnplacedCandidate,
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


def _hm(start, end):
    """晨卡（从酒店出发）：识别只看 item_id 前缀。"""
    return _v("hotel-morning-d1", "出发", start, end, cat="hotel")


def _food(name, start, end, lon=121.49, lat=31.24):
    return _v(name, name, start, end, cat="food", lon=lon, lat=lat)


def _cand(name, dur, lon=121.52, lat=31.20, *, cat="sight"):
    return UnplacedCandidate(
        name=name,
        category=cat,
        duration_minutes=dur,
        location=GeoPoint(lon=lon, lat=lat),
        city="上海",
        poi_id=name,
    )


def _plan(items, *, assumptions=None):
    return ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=items)],
        assumptions=list(assumptions or []),
    )


def _placed(plan, name):
    return next(i for i in plan.days[0].items if i.name == name)


def test_fill_starts_after_hotel_morning_card():
    """晨卡 10:30-11:00：补点不得排到出发卡之前（旧口径 08:30 就出门）。"""
    plan = _plan(
        [_hm(time(10, 30), time(11, 0)), _food("晚饭", time(19, 0), time(20, 30))]
    )
    notes = _fill_leftover_with_diverse_sights(plan, bench=[_cand("测试景点", 90)])
    assert notes
    assert _placed(plan, "测试景点").start_time >= time(11, 0)


def test_fill_does_not_overlap_real_lunch_card():
    """真实午饭 11:45-12:45 是墙：补点只能从餐后开始。"""
    plan = _plan(
        [
            _hm(time(11, 0), time(11, 30)),
            _food("午饭", time(11, 45), time(12, 45)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    notes = _fill_leftover_with_diverse_sights(plan, bench=[_cand("测试景点", 60)])
    assert notes
    placed = _placed(plan, "测试景点")
    assert placed.start_time >= time(12, 45)
    assert placed.start_time != time(11, 45)


def test_heavy_day_still_takes_a_short_sight():
    """重日（必去 180+120=300）仍有空档时，≤90 分钟的短件要补得进来。"""
    plan = _plan(
        [
            _v(
                "m",
                "博物馆",
                time(9, 0),
                time(12, 0),
                cat="museum",
                must=True,
                dur=180,
            ),
            _food("午饭", time(12, 0), time(13, 0)),
            _v(
                "bund",
                "外滩",
                time(17, 0),
                time(19, 0),
                cat="nature",
                must=True,
                dur=120,
            ),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    notes = _fill_leftover_with_diverse_sights(
        plan, bench=[_cand("短景点", 60, 121.55, 31.18)]
    )
    assert notes
    assert _placed(plan, "短景点").start_time == time(13, 0)


def test_fill_skips_day_with_four_sights():
    """一天已 4 张观光卡：补点不再加第 5 张（与选点期同口径）。"""
    plan = _plan(
        [
            _v("a", "景点A", time(9, 0), time(10, 0), lon=121.40, lat=31.20),
            _v("b", "景点B", time(10, 30), time(11, 30), lon=121.44, lat=31.24),
            _v("c", "景点C", time(14, 0), time(15, 0), lon=121.50, lat=31.28),
            _v("d", "景点D", time(15, 30), time(16, 30), lon=121.54, lat=31.20),
            _food("午饭", time(12, 0), time(13, 0)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("第五个", 90)]) == []


def test_fill_skips_micro_gaps_and_micro_sights():
    """45 分钟空档 + 30 分钟件：都不补（边角料只是凑数）。"""
    plan = _plan(
        [
            _hm(time(10, 30), time(11, 0)),
            _food("午饭", time(11, 45), time(12, 45)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("观景厅", 30)]) == []


def test_fill_is_idempotent_via_disclosure_marker():
    """披露即标记：同一份行程第二次补点必须空转（开页刷新不叠加）。"""
    plan = _plan(
        [_hm(time(10, 30), time(11, 0)), _food("晚饭", time(19, 0), time(20, 30))]
    )
    first = _fill_leftover_with_diverse_sights(plan, bench=[_cand("测试景点", 90)])
    assert first
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("另一个点", 90)]) == []


class _FakeDetails:
    def top_pois_in_city(self, city, limit=30, **kw):
        return [
            {
                "poi_id": "bench-1",
                "name": "库内景点",
                "category": "sight",
                "tier": 2,
                "suggested_duration_min": 90,
                "location": (121.52, 31.20),
                "tags": [],
            }
        ]


def test_fill_leftover_gaps_appends_notes_and_is_session_idempotent():
    plan = _plan(
        [_hm(time(10, 30), time(11, 0)), _food("晚饭", time(19, 0), time(20, 30))]
    )
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._poi_details = _FakeDetails()
    session = PlanSession(
        session_id="s1", device_id="d1", cities=["上海"], days=1, plan=plan
    )
    notes = asyncio.run(agent.fill_leftover_gaps(session))
    assert notes
    assert all(n in session.plan.assumptions for n in notes)
    assert asyncio.run(agent.fill_leftover_gaps(session)) == []
