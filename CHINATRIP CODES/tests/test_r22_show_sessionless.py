# -*- coding: utf-8 -*-
"""R22 regression tests: sessionless shows are placeable from noon.

2026-11-11 拍板「无场次 SHOW 下午或晚上」在 legacy solver._visit_spec 一直生效
（lo=max(lo, SHOW_AFTERNOON_START_MINUTES)），引擎 C-11 的初版移植（b4f3411）
却把 sessionless 与 off_season 一起 lit==0 整卡禁排——必去组合直接
INFEASIBLE 整单回落 legacy，库内 5 行无场次 show（大唐不夜城/汉秀/两个戏剧
幻城/丝路花雨）在引擎侧永远不可排。修复：sessionless → 硬窗 start≥12:00
（偏好层 SHOW_EARLY_PENALTY 自然压 ≥15:00）；off_season（冬季停演）保持禁排；
真场次 AddAllowedAssignments 硬钉不变。
"""

from app.services.trip_solver.entry import ENGINE_CPSAT, solve_trip
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TripRequest,
)

SHOW_LON, SHOW_LAT = 108.9554, 34.2116
SESSIONS = (14 * 60, 16 * 60 + 30, 19 * 60 + 30)


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


def _solve(hours):
    req = RequestedItem(rid="r1", name="大唐不夜城", poi_id="poi_c1", kind="must")
    show = CandidateItem(
        cid="c1",
        name="大唐不夜城",
        poi_id="poi_c1",
        kind="requested",
        rid="r1",
        category="entertainment",
        tier=4,
        lon=SHOW_LON,
        lat=SHOW_LAT,
        opening_hours=hours,
        best_visit_time="show",
        suggested_duration_min=80,
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
        candidates=(show, _rival()),
        source="r22-test",
    )
    return solve_trip(snap, flag=ENGINE_CPSAT, budget_s=20.0, fail_loud=True).solution


def _show_start(sol):
    items = [i for i in sol.items if i.cid == "c1"]
    assert items, "sessionless show must be placeable; unplaced=%r" % (sol.unplaced,)
    return items[0].start_min


def test_sessionless_show_must_placeable_from_noon():
    sol = _solve("9:00-21:00")
    assert sol.status == "OPTIMAL"
    assert _show_start(sol) >= 12 * 60


def test_rolling_sessionless_show_placeable():
    # 真实库文本：夜间街区演艺（约16:30-22:00滚动，不倒翁约19:00起）
    sol = _solve("夜间街区演艺（约16:30-22:00滚动，不倒翁约19:00起）")
    assert sol.status == "OPTIMAL"
    assert _show_start(sol) >= 12 * 60


def test_real_sessions_still_pinned():
    sol = _solve("多场（约14:00/16:30/19:30）")
    assert sol.status == "OPTIMAL"
    assert _show_start(sol) in SESSIONS


def test_off_season_show_still_dropped():
    # 冬季停演 + 12 月行程 = 演出季外 → 真不可演，保持禁排（legacy 同口径）。
    sol = _solve("冬季停演")
    assert sol.status == "OPTIMAL"
    assert not [i for i in sol.items if i.cid == "c1"]
    assert sol.unplaced, "show must land in unplaced with a reason"
