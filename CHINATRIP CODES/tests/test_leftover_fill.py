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


def _cand(name, dur, lon=121.52, lat=31.20, *, cat="sight", bvt=None):
    return UnplacedCandidate(
        name=name,
        category=cat,
        duration_minutes=dur,
        location=GeoPoint(lon=lon, lat=lat),
        city="上海",
        poi_id=name,
        best_visit_time=bvt,
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
        plan, bench=[_cand("短景点", 60, 121.50, 31.22)]
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


def test_evening_candidate_never_before_five_pm():
    """best_visit_time=evening 的件不得排到 17:00 之前（浦江游览 12:45 案）。"""
    plan = _plan(
        [
            _hm(time(8, 30), time(9, 0)),
            _food("午饭", time(12, 0), time(13, 0)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    notes = _fill_leftover_with_diverse_sights(
        plan, bench=[_cand("浦江夜游", 120, bvt="evening")]
    )
    assert notes
    placed = _placed(plan, "浦江夜游")
    assert placed.start_time >= time(17, 0)
    assert placed.end_time <= time(19, 0)


def test_fill_refills_morning_when_card_moved_back_to_day_start():
    """晨卡回拨日始后上午空出来：已有「补过」标记也要再补一次（上海 D1）。"""
    card = _hm(time(8, 30), time(9, 0))
    plan = _plan(
        [
            card,
            _food("午饭", time(11, 45), time(12, 45)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ],
        assumptions=["第1天还有空档，按类型多样性补了「黄浦江游览」（12:45）"],
    )
    notes = _fill_leftover_with_diverse_sights(plan, bench=[_cand("豫园", 90)])
    assert notes
    placed = _placed(plan, "豫园")
    assert placed.start_time == time(9, 0)
    assert placed.end_time == time(10, 30)
    # 补完上午不再有 opening hole → 第二次必须空转（不越补越多）
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("另一个点", 90)]) == []


def test_fill_keeps_skipping_filled_day_without_opening_hole():
    """已补过 + 首件就在日始：仍是零改动（旧幂等口径不回退）。"""
    plan = _plan(
        [
            _hm(time(8, 30), time(9, 0)),
            _v("a", "景点A", time(9, 0), time(10, 30), lon=121.44, lat=31.24),
            _food("午饭", time(11, 45), time(12, 45)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ],
        assumptions=["第1天还有空档，按类型多样性补了「景点A」（09:00）"],
    )
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("豫园", 90)]) == []


def test_fill_uses_afternoon_after_incity_return_leg():
    """同城回城腿（access-*）不套 90 分钟跨城缓冲：15:01 落地后下午要能用。

    2026-11-16 用户「day1 回城以后才三四点，为什么不安排其它节目？」：
    朱家角回城卡 14:00-15:01 被旧口径铺成 12:30-16:31，普通件进场闸
    15:30 之后整段下午判死，补点永远补不进来。
    """
    from app.services.agent.plan import _day_fixed_windows
    from app.services.itinerary.models import TransferItem

    ret = TransferItem(
        item_id="access-return-extras-2-朱家角大清邮局",
        day=2,
        seq=0,
        from_city="",
        to_city="",
        mode="car",
        start_time=time(14, 0),
        end_time=time(15, 1),
        duration_minutes=61,
    )
    day = DayPlan(
        day=2,
        base_city="上海",
        items=[
            _hm(time(8, 30), time(9, 0)),
            _v(
                "zjj",
                "朱家角古镇",
                time(9, 0),
                time(12, 0),
                cat="attraction",
                lon=121.05,
                lat=31.11,
            ),
            _food("午饭", time(12, 0), time(13, 0)),
            _v(
                "post",
                "大清邮局",
                time(13, 10),
                time(14, 10),
                cat="other",
                lon=121.05,
                lat=31.11,
            ),
            ret,
            _food("晚饭", time(19, 10), time(20, 40)),
        ],
    )
    fixed, _tight, _flex, _xfer = _day_fixed_windows(day)
    win = next(w for w in fixed if w[2] is None)
    # 只有 15 分钟换乘余量，不是 ±90 跨城缓冲
    assert win[:2] == (14 * 60 - 15, 15 * 60 + 1 + 15)
    plan = ItineraryPlan(itinerary_id="t", cities=["上海"], days=[day], assumptions=[])
    notes = _fill_leftover_with_diverse_sights(
        plan, bench=[_cand("田子坊", 90, 121.47, 31.21)]
    )
    assert notes
    placed = next(i for i in day.items if getattr(i, "name", "") == "田子坊")
    assert placed.start_time >= time(15, 1)
    assert placed.end_time <= time(19, 0)


def test_intercity_transfer_keeps_ninety_minute_buffer():
    """真跨城腿仍是铁律 4 的 90 分钟衔接缓冲（别把同城口径扩大化）。"""
    from app.services.agent.plan import _day_fixed_windows
    from app.services.itinerary.models import TransferItem

    leg = TransferItem(
        item_id="x1",
        day=1,
        seq=0,
        from_city="上海",
        to_city="北京",
        mode="train",
        start_time=time(14, 0),
        end_time=time(18, 0),
        duration_minutes=240,
    )
    day = DayPlan(day=1, base_city="上海", items=[leg])
    from app.services.itinerary.models import arrival_floor_minutes

    fixed, _tight, _flex, _xfer = _day_fixed_windows(day)
    win = next(w for w in fixed if w[2] is None)
    assert win[:2] == (14 * 60 - 90, 18 * 60 + arrival_floor_minutes("train"))


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
