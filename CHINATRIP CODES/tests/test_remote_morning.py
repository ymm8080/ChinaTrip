# -*- coding: utf-8 -*-
"""远郊景点上午开场（2026-11-15 用户拍板「远郊景点 BEST VISIT TIME MORNING」）。

口径：装配期按距城心 >_DAY_MIX_KM 打 VisitItem.remote（plan._mark_remote_visits，
与日间混排闸同源锚表）；引擎侧三件事——远郊件恒为头档候选（先抢上午头档）、
12:00 后开场计软罚、兜底排序远郊件先落位。软偏好不拦可行性：上午被钉住件占死
时照付罚放行，绝不把远郊件判成排不下。
"""

from datetime import time as _t

from app.services.agent.plan import (
    PlanningAgent,
    _fallback_sequence_times,
    _mark_remote_visits,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.itinerary.solver import (
    REMOTE_AFTERNOON_MINUTES,
    _is_head_candidate,
    solve_day,
)

BJ = (116.4074, 39.9042)  # 北京城心（lon, lat）


def _visit(item_id, name, *, dur, tier=None, lon=None, lat=None, city="北京", **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city=city,
        day=1,
        duration_minutes=dur,
        tier=tier,
        category="sight",
        location=None if lon is None else GeoPoint(lon=lon, lat=lat),
    )
    base.update(kw)
    return VisitItem(**base)


def _minutes(v: VisitItem) -> int:
    assert v.start_time is not None
    return v.start_time.hour * 60 + v.start_time.minute


def test_remote_visit_is_always_head_candidate():
    # 远郊件 tier 再低（9）也是头档候选；夜属性/餐/演出不进。
    assert _is_head_candidate(_visit("mt", "慕田峪长城", dur=210, tier=9, remote=True))
    assert not _is_head_candidate(_visit("mt", "慕田峪长城", dur=210, tier=9))
    assert not _is_head_candidate(
        _visit(
            "ng",
            "古北水镇夜游",
            dur=120,
            tier=2,
            remote=True,
            best_visit_time="evening",
        )
    )
    assert not _is_head_candidate(
        _visit("fd", "慕田峪餐厅", dur=60, tier=2, remote=True, category="food")
    )


def test_solver_schedules_remote_sight_in_the_morning():
    # 远郊 210 分钟 + 城心 90 分钟：远郊件吃上午头档（08:30 开场），城心件让到午后。
    far = _visit(
        "mt", "慕田峪长城", dur=210, tier=9, lon=116.5646, lat=40.4319, remote=True
    )
    city = _visit("gug", "故宫博物院", dur=90, tier=2, lon=116.3970, lat=39.9163)
    out = solve_day(DayPlan(day=1, base_city="北京", items=[city, far]), poi_hours=[])
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    assert starts["mt"] < REMOTE_AFTERNOON_MINUTES
    assert starts["mt"] < starts["gug"]


def test_remote_late_penalty_soft_not_infeasible():
    # 上午被用户钉死件占掉（09:00-11:30）：远郊件照付罚放行，仍出时刻（不判排不下）。
    pin = _visit(
        "flag",
        "天安门广场",
        dur=150,
        tier=1,
        lon=116.3975,
        lat=39.9087,
        pinned=True,
        start_time=_t(9, 0),
        end_time=_t(11, 30),
    )
    far = _visit(
        "mt", "慕田峪长城", dur=180, tier=9, lon=116.5646, lat=40.4319, remote=True
    )
    out = solve_day(DayPlan(day=1, base_city="北京", items=[pin, far]), poi_hours=[])
    assert out is not None
    timed = {v.item_id: v for v in out.items if isinstance(v, VisitItem)}
    assert timed["flag"].start_time == _t(9, 0)  # 铁律 19 不动
    assert timed["mt"].start_time is not None  # 排不下 = None，这里必须有时刻


def test_mark_remote_visits_by_city_center():
    plan = ItineraryPlan(
        itinerary_id="it-remote",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    _visit("mt", "慕田峪长城", dur=210, lon=116.5646, lat=40.4319),
                    _visit("gug", "故宫博物院", dur=120, lon=116.3970, lat=39.9163),
                    _visit(
                        "gz",
                        "古北水镇夜游",
                        dur=120,
                        lon=117.1000,
                        lat=40.6500,
                        best_visit_time="evening",
                    ),
                    _visit(
                        "fd",
                        "慕田峪餐厅",
                        dur=60,
                        lon=116.5600,
                        lat=40.4300,
                        category="food",
                    ),
                ],
            )
        ],
    )
    marked = _mark_remote_visits(plan)
    flags = {
        i.item_id: i.remote
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem)
    }
    assert flags == {"mt": True, "gug": False, "gz": False, "fd": False}
    assert marked == 1


def test_fallback_sequence_puts_remote_first():
    # 兜底排序（无 solver 解时）：远郊件排早、城心件在后。
    far = _visit("mt", "慕田峪长城", dur=180, tier=9, lon=116.5646, lat=40.4319)
    city = _visit("gug", "故宫博物院", dur=90, tier=2, lon=116.3970, lat=39.9163)
    plan = ItineraryPlan(
        itinerary_id="it-fb",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[city, far])],
    )
    _fallback_sequence_times(plan)
    items = [i for i in plan.days[0].items if isinstance(i, VisitItem)]
    starts = {i.item_id: _minutes(i) for i in items if i.start_time is not None}
    assert starts["mt"] < starts["gug"]
    assert starts["mt"] < REMOTE_AFTERNOON_MINUTES


def test_deterministic_selection_keeps_remote_day_apart():
    # 回归护栏：远郊打标不改「远郊件不与城心簇同日」（分天口径仍由混排闸管）。
    cands = [
        {
            "name": "故宫博物院",
            "city": "北京",
            "category": "attraction",
            "suggested_duration_min": 120,
            "location": {"lon": 116.397, "lat": 39.9163},
        },
        {
            "name": "天安门广场",
            "city": "北京",
            "category": "attraction",
            "suggested_duration_min": 90,
            "location": {"lon": 116.3975, "lat": 39.9087},
        },
        {
            "name": "慕田峪长城",
            "city": "北京",
            "category": "attraction",
            "suggested_duration_min": 210,
            "location": {"lon": 116.5646, "lat": 40.4319},
        },
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"北京": (1, 2)})
    mt = next((it for it in items if it["name"] == "慕田峪长城"), None)
    city_days = {
        it["day"] for it in items if it["name"] in ("故宫博物院", "天安门广场")
    }
    if mt is not None:
        assert mt["day"] not in city_days
