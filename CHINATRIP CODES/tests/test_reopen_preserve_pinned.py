# -*- coding: utf-8 -*-
"""reopen 保位（2026-11-17 用户「不接受遗留：重开挤掉慕田峪」）：
重开已存行程（source_itinerary_id 在）时，已带时刻的 pinned/must 卡是硬锚——
族定天不挪、远郊分离不清、钉时探针不与之重叠、让位梯不 eject；新必去只落
真空档，落不进保持灰卡+披露。"""

from __future__ import annotations

import asyncio
from datetime import time

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    _assign_must_family_days,
    _mark_remote_visits,
    _pin_musts_by_importance,
    _separate_remote_must_days,
)
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem

TIANANMEN = GeoPoint(lon=116.4074, lat=39.9042)
GUGONG = GeoPoint(lon=116.4097, lat=39.9130)
MUTIANYU = GeoPoint(lon=116.5598, lat=40.4267)
YIHEYUAN = GeoPoint(lon=116.2733, lat=39.9990)


def _v(item_id, name, start, end, *, cat="sight", lon=None, lat=None, day=1, **kw):
    dur = None
    if start is not None and end is not None:
        dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return VisitItem(
        item_id=item_id,
        name=name,
        city="北京",
        day=day,
        category=cat,
        duration_minutes=kw.pop("dur", dur),
        location=GeoPoint(lon=lon, lat=lat) if lon is not None else None,
        start_time=start,
        end_time=end,
        **kw,
    )


def _saved_shape_plan():
    """按用户保存的 it-e1dc1261 形状构造：D1 天安门+慕田峪（均已排），
    D2 故宫+天坛（已排）+颐和园（must 灰卡无时刻）。"""
    d1 = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _v("hotel-morning-d1", "出发", time(6, 15), time(6, 45), cat="hotel"),
            _v(
                "v21",
                "天安门广场",
                time(7, 15),
                time(8, 45),
                cat="square",
                lon=TIANANMEN.lon,
                lat=TIANANMEN.lat,
                dur=90,
                pinned=True,
                must=True,
            ),
            _v(
                "v24",
                "慕田峪长城",
                time(11, 38),
                time(14, 38),
                cat="nature",
                lon=MUTIANYU.lon,
                lat=MUTIANYU.lat,
                dur=180,
                pinned=True,
                must=True,
            ),
            _v(
                "food-lunch-ph-d1",
                "午饭（自由安排）",
                time(14, 38),
                time(15, 38),
                cat="food",
                lon=MUTIANYU.lon,
                lat=MUTIANYU.lat,
                anchor_from_prev=True,
                anchor_location=MUTIANYU,
            ),
            _v(
                "food-dinner-ph-d1",
                "晚饭（自由安排）",
                time(19, 0),
                time(20, 30),
                cat="food",
            ),
            _v("hotel-night-d1", "回酒店", time(21, 0), time(22, 0), cat="hotel"),
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="北京",
        items=[
            _v("hotel-morning-d2", "出发", time(8, 30), time(9, 0), cat="hotel", day=2),
            _v(
                "v20",
                "故宫博物院",
                time(9, 0),
                time(11, 0),
                cat="museum",
                lon=GUGONG.lon,
                lat=GUGONG.lat,
                dur=120,
                pinned=True,
                must=True,
                day=2,
            ),
            _v(
                "v22",
                "天坛",
                time(12, 0),
                time(14, 30),
                cat="park",
                lon=116.4107,
                lat=39.8822,
                dur=150,
                pinned=True,
                must=True,
                day=2,
            ),
            _v(
                "v25",
                "颐和园",
                None,
                None,
                cat="park",
                lon=YIHEYUAN.lon,
                lat=YIHEYUAN.lat,
                dur=300,
                pinned=True,
                must=True,
                day=2,
            ),
            _v(
                "food-dinner-ph-d2",
                "晚饭（自由安排）",
                time(19, 0),
                time(20, 30),
                cat="food",
                day=2,
            ),
            _v(
                "hotel-night-d2", "回酒店", time(21, 0), time(22, 0), cat="hotel", day=2
            ),
        ],
    )
    return ItineraryPlan(
        itinerary_id="it-test",
        cities=["北京"],
        days=[d1, d2],
        assumptions=[],
    )


def _timed(plan, name):
    for d in plan.days:
        for i in d.items:
            if i.name == name:
                return i
    raise AssertionError(f"{name} not found")


def _no_overlap_with(plan, name):
    me = _timed(plan, name)
    assert me.start_time is not None, f"{name} lost its slot"
    for d in plan.days:
        timed = sorted(
            (
                i
                for i in d.items
                if isinstance(i, VisitItem)
                and i.start_time is not None
                and i is not me
                and i.day == me.day
                and (i.category or "") not in ("food", "hotel")
            ),
            key=lambda i: i.start_time,
        )
        for o in timed:
            assert not (me.start_time < o.end_time and o.start_time < me.end_time), (
                f"{name} overlaps {o.name}"
            )


def test_assign_family_preserve_keeps_timed_card_on_its_day():
    plan = _saved_shape_plan()
    _assign_must_family_days(plan, preserve_timed=True)
    tiananmen = _timed(plan, "天安门广场")
    assert tiananmen.day == 1
    assert tiananmen.start_time == time(7, 15)
    # 对照：不保位时族定天可挪（旧行为不回归即可运行）
    plan2 = _saved_shape_plan()
    _assign_must_family_days(plan2, preserve_timed=False)


def test_pin_musts_preserve_keeps_timed_slot():
    plan = _saved_shape_plan()
    _pin_musts_by_importance(plan, preserve_timed=True)
    mty = _timed(plan, "慕田峪长城")
    assert (mty.start_time.hour, mty.start_time.minute) == (11, 38)
    assert mty.end_time == time(14, 38)
    _no_overlap_with(plan, "慕田峪长城")
    _no_overlap_with(plan, "天安门广场")


def test_separate_remote_preserve_keeps_timed_musts():
    plan = _saved_shape_plan()
    _mark_remote_visits(plan)
    _separate_remote_must_days(plan, preserve_timed=True)
    mty = _timed(plan, "慕田峪长城")
    assert mty.start_time == time(11, 38)
    tiananmen = _timed(plan, "天安门广场")
    assert tiananmen.start_time == time(7, 15)


def test_heal_reopen_keeps_mutianyu_slot_end_to_end():
    plan = _saved_shape_plan()
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._poi_details = None
    session = PlanSession(
        session_id="s-reopen",
        device_id="d-reopen",
        cities=["北京"],
        days=2,
        state="ready",
        plan=plan,
        source_itinerary_id="it-e1dc1261",
        must_visits=["慕田峪长城", "天安门广场", "故宫博物院", "天坛", "颐和园"],
    )
    asyncio.run(agent.heal_must_coverage(session))
    mty = _timed(session.plan, "慕田峪长城")
    assert mty.day == 1 and mty.start_time is not None
    # 两种合法终态：槽位原样 11:38-14:38；或先午餐后游览 12:38-15:38
    assert mty.start_time in (time(11, 38), time(12, 38))
    if mty.start_time == time(12, 38):
        assert mty.end_time == time(15, 38)
    else:
        assert mty.end_time == time(14, 38)
    tiananmen = _timed(session.plan, "天安门广场")
    assert tiananmen.start_time == time(7, 15)
    _no_overlap_with(session.plan, "慕田峪长城")
    _no_overlap_with(session.plan, "天安门广场")
    yihe = _timed(session.plan, "颐和园")
    if yihe.start_time is not None:
        _no_overlap_with(session.plan, "颐和园")
