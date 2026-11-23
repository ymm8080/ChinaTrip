# -*- coding: utf-8 -*-
"""R19（2026-11-23 兵马俑案）回归三件：

① C-08 接驳档案 outbound 有班、return 为空（真库 poi_access_services
   在册形态，如北京 居庸关长城/八奇洞、上海 东林寺/州桥老街）此前
   min(rets) 直接 ValueError——引擎整缝崩、回落 legacy，是「兵马俑未
   排」根因链之一；
② 覆盖审计 poi_id 键匹配：别名必去（兵马俑 ↔ 秦始皇帝陵博物院）名
   匹配恒 miss，键命中已排卡/想去 chip 即算已排（H5「必去未排上」
   横幅误报根因）；
③ 覆盖审计键匹配负向锚：键不命中仍如实报未排（不许 poi 键放水）。
"""

from __future__ import annotations

from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    UnplacedCandidate,
    VisitItem,
)
from app.services.itinerary.request_coverage import (
    ensure_must_disclosure,
    missing_must_visits,
    unarranged_must_visits,
)
from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.c01_c04 import build_model
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.types import (
    AccessProfile,
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TripRequest,
)


def _snapshot_empty_returns():
    remote = CandidateItem(
        cid="cr",
        name="秦始皇帝陵博物院",
        poi_id="5a_296",
        kind="requested",
        rid="r1",
        category="sight",
        opening_hours="08:00-18:00",
        suggested_duration_min=150,
        lon=109.28,
        lat=34.38,
        remote=True,
    )
    other = CandidateItem(
        cid="co",
        name="西安博物院",
        poi_id="m2_xa",
        kind="requested",
        rid="r2",
        category="museum",
        opening_hours="09:00-17:00",
        suggested_duration_min=90,
        lon=108.94,
        lat=34.23,
    )
    return FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=1,
            cities=("西安",),
            musts=(
                RequestedItem(rid="r1", name="秦始皇帝陵博物院", poi_id="5a_296"),
                RequestedItem(rid="r2", name="西安博物院", poi_id="m2_xa"),
            ),
        ),
        candidates=(remote, other),
        access_profiles=(
            AccessProfile(
                gateway="乘车点",
                to_poi="5a_296",
                ride_minutes=60,
                last_mile_minutes=8,
                departures=("09:30",),
                returns=(),
                mode="shuttle",
            ),
        ),
        source="synthetic",
    )


def test_c08_empty_returns_profile_builds_model():
    """outbound 有班、return 空：build_model 不再 ValueError（R19 前实锤
    「min() iterable argument is empty」→ 引擎整缝崩、回落 legacy）。"""
    snapshot = _snapshot_empty_returns()
    bundle = build_model(enrich(snapshot))
    assert bundle is not None


def test_c08_empty_returns_profile_still_solves():
    """空 return 行不灭活档案：带档案的远郊必去仍带接驳链排进当天
    （unplaced 里不得出现它；另一必去在 1 天玩具盘里允许诚实容量让位）。"""
    snapshot = _snapshot_empty_returns()
    solution = solve_snapshot(enrich(snapshot), budget_s=3.0)
    assert solution.status in ("OPTIMAL", "FEASIBLE")
    unplaced_rids = {str(e.get("rid") or "") for e in (solution.unplaced or [])}
    assert "r1" not in unplaced_rids  # 带空-return 档案的远郊必去在场
    placed = {it.cid for it in solution.items}
    assert "cr" in placed


# ---------------- ② 覆盖审计 poi_id 键匹配 ----------------


def _xa_plan():
    return ItineraryPlan(
        itinerary_id="it-xa",
        cities=["西安"],
        days=[
            DayPlan(
                day=1,
                base_city="西安",
                items=[
                    VisitItem(
                        item_id="v1",
                        name="秦始皇帝陵博物院",
                        poi_id="5a_296",
                        city="西安",
                        day=1,
                    )
                ],
            )
        ],
        assumptions=[],
        unplaced=[],
    )


def test_unarranged_matches_by_poi_binding():
    plan = _xa_plan()
    # 旧口径（纯名匹配）：兵马俑 ↔ 秦始皇帝陵博物院 恒 miss → 横幅误报
    assert unarranged_must_visits(plan, ["兵马俑"]) == ["兵马俑"]
    # 键匹配：poi_id 命中已排卡 → 已排（2026-11-23 兵马俑案根修）
    assert (
        unarranged_must_visits(plan, ["兵马俑"], must_poi_ids={"兵马俑": "5a_296"})
        == []
    )


def test_missing_and_disclosure_respect_poi_binding():
    plan = _xa_plan()
    must = ["兵马俑"]
    assert missing_must_visits(plan, must) == ["兵马俑"]
    assert missing_must_visits(plan, must, must_poi_ids={"兵马俑": "5a_296"}) == []
    assert ensure_must_disclosure(plan, must, must_poi_ids={"兵马俑": "5a_296"}) == []
    # 不再误补「未排入行程」披露（引擎明明已把必去排成卡）
    assert plan.assumptions == []


def test_poi_binding_still_flags_when_poi_not_scheduled():
    """负向锚：键不命中（另一 POI）仍如实报未排——键匹配不放水。"""
    plan = _xa_plan()
    assert unarranged_must_visits(
        plan, ["兵马俑"], must_poi_ids={"兵马俑": "other_id"}
    ) == ["兵马俑"]
    assert missing_must_visits(
        plan, ["兵马俑"], must_poi_ids={"兵马俑": "other_id"}
    ) == ["兵马俑"]


def test_poi_binding_matches_unplaced_chip():
    """想去 chip 也认键：poi 在 unplaced（附原因）不算静默丢失。

    unarranged_musts 横幅口径不变——chip 不是天卡，未排上照报
    （2026-11-17 一日游案契约）；missing（静默丢失）侧认键：chip 已是
    可见告知面，不补「未排入行程」披露。"""
    plan = _xa_plan()
    plan.days[0].items = []
    plan.unplaced = [
        UnplacedCandidate(
            name="秦始皇帝陵博物院", poi_id="5a_296", reason="cluster_day"
        )
    ]
    # 横幅如实报「未排上」（想去 chip 不算排入）
    assert unarranged_must_visits(
        plan, ["兵马俑"], must_poi_ids={"兵马俑": "5a_296"}
    ) == ["兵马俑"]
    # 静默丢失审计认键：chip 可见 → 覆盖契约满足
    assert (
        missing_must_visits(plan, ["兵马俑"], must_poi_ids={"兵马俑": "5a_296"}) == []
    )
    assert (
        ensure_must_disclosure(plan, ["兵马俑"], must_poi_ids={"兵马俑": "5a_296"})
        == []
    )
