# -*- coding: utf-8 -*-
"""R23 regression tests: morning/afternoon/sunset slot windows in C-01.

镜像 legacy itinerary/solver.py:_BEST_VISIT_WINDOWS 三槽（morning 8:30-12:00 /
afternoon 12:00-17:00 / sunset 16:00-19:00，end 落窗内）。引擎此前对这三槽
零消费（72 行库数据的「晨景/午后最佳/黄昏」语义静默丢失）。放不下 →
presence=0 弃卡（与 legacy unplaced 同形）；evening 保持 R20 软阶梯、sunrise
走旗时等式、show 走 C-11 场次钉，均不在本表。
"""

from app.services.trip_solver.entry import ENGINE_CPSAT, solve_trip
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TripRequest,
)


def _rival():
    return CandidateItem(
        cid="c2",
        name="小雁塔",
        poi_id="poi_c2",
        kind="fill",
        category="sight",
        tier=4,
        lon=108.9375,
        lat=34.2360,
        opening_hours="09:00-17:00",
        suggested_duration_min=75,
        city="西安",
    )


def _solve(bvt, dur):
    req = RequestedItem(rid="r1", name="晨景楼", poi_id="poi_c1", kind="must")
    poi = CandidateItem(
        cid="c1",
        name="晨景楼",
        poi_id="poi_c1",
        kind="requested",
        rid="r1",
        category="sight",
        tier=4,
        lon=108.9554,
        lat=34.2116,
        opening_hours="全天开放",
        best_visit_time=bvt,
        suggested_duration_min=dur,
        city="西安",
    )
    snap = FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=1,
            cities=("西安",),
            start_date="2026-12-01",
            musts=(req,),
            wishes=(),
        ),
        candidates=(poi, _rival()),
        source="r23-test",
    )
    return solve_trip(snap, flag=ENGINE_CPSAT, budget_s=20.0, fail_loud=True).solution


def _poi(sol):
    items = [i for i in sol.items if i.cid == "c1"]
    return items[0] if items else None


def test_morning_poi_ends_by_noon():
    sol = _solve("morning", 90)
    assert sol.status == "OPTIMAL"
    it = _poi(sol)
    assert it is not None, "morning poi must be placeable; unplaced=%r" % (
        sol.unplaced,
    )
    assert it.end_min <= 12 * 60


def test_afternoon_poi_inside_afternoon_window():
    sol = _solve("afternoon", 90)
    assert sol.status == "OPTIMAL"
    it = _poi(sol)
    assert it is not None
    assert it.start_min >= 12 * 60
    assert it.end_min <= 17 * 60


def test_sunset_poi_inside_dusk_window():
    sol = _solve("sunset", 90)
    assert sol.status == "OPTIMAL"
    it = _poi(sol)
    assert it is not None
    assert it.start_min >= 16 * 60
    assert it.end_min <= 19 * 60


def test_morning_long_poi_dropped_when_window_infeasible():
    # 240 分钟晨景卡从 8:30 起不可能在 12:00 前结束 → 弃卡留痕（legacy 同形；
    # 时长收缩不覆盖槽位窗——实测证伪收缩救援，按实写）。注意：必去被弃后
    # 填充同落的空计划形态=R14⑦a/R19①已挂账缺陷族（并行会话在飞修复），
    # 本测不断言填充去留。
    sol = _solve("morning", 240)
    assert sol.status == "OPTIMAL"
    assert _poi(sol) is None
    assert sol.unplaced


def test_morning_window_fail_open_drops_when_hours_conflict():
    # 槽位窗（≤12:00）与营业窗（14:00-18:00）互斥 → 没有任何可行起点 →
    # presence=0 弃卡留痕（legacy unplaced 同形）。
    req = RequestedItem(rid="r1", name="晨景楼", poi_id="poi_c1", kind="must")
    poi = CandidateItem(
        cid="c1",
        name="晨景楼",
        poi_id="poi_c1",
        kind="requested",
        rid="r1",
        category="sight",
        tier=4,
        lon=108.9554,
        lat=34.2116,
        opening_hours="14:00-18:00",
        best_visit_time="morning",
        suggested_duration_min=90,
        city="西安",
    )
    snap = FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=1,
            cities=("西安",),
            start_date="2026-12-01",
            musts=(req,),
            wishes=(),
        ),
        candidates=(poi, _rival()),
        source="r23-test",
    )
    sol = solve_trip(snap, flag=ENGINE_CPSAT, budget_s=20.0, fail_loud=True).solution
    assert sol.status == "OPTIMAL"
    assert _poi(sol) is None
    assert sol.unplaced
