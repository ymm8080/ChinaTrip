# -*- coding: utf-8 -*-
"""R31 (2026-11-24): user-written day plan outranks C-06 remote-day
exclusivity.

Live failure (session b2d34fea307147cc87e508cf4c31f16d): 用户 keep 了写明
日程 —— D2 天坛/什刹海/南锣鼓巷, D3 慕田峪长城/北京奥林匹克公园/国家体育场。
C-25 把每组做成硬同日块; C-06 却禁止远郊日放两个城市点, 于是「全部必去都
排入」不可行, 最小弃排梯丢掉 什刹海 与 鸟巢(国家体育场), 而当天上午仍有
大段空白。修:C-06 在用户写明天时让位(物理接驳序仍由 C-08 独立保证)。
"""

from __future__ import annotations

from types import SimpleNamespace

from ortools.sat.python import cp_model

from app.services.trip_solver.assembly.disclosures import render_disclosures
from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.c05_c08 import add_c06_remote_exclusivity
from app.services.trip_solver.model.c25_must_days import has_user_day_blocks
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.types import (
    AccessProfile,
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    Solution,
    SolutionItem,
    TripRequest,
)

REMOTE = "mtu"
A, B = "olympic_park", "bird_nest"


# --- focused C-06 unit world ------------------------------------------------
def _c06_world(*, with_day_hints: bool):
    """remote + 2 城市点同日; C-06 生效时应因 extras<=1 不可行。"""
    hint = 1 if with_day_hints else None
    cands = [
        SimpleNamespace(
            cid="cR", rid="rR", poi_id=REMOTE, category="sight",
            suggested_duration_min=180,
        ),
        SimpleNamespace(
            cid="cA", rid="rA", poi_id="pa", category="sight",
            suggested_duration_min=90,
        ),
        SimpleNamespace(
            cid="cB", rid="rB", poi_id="pb", category="sight",
            suggested_duration_min=90,
        ),
    ]
    request = SimpleNamespace(
        days=1,
        musts=[
            SimpleNamespace(rid="rR", day_hint=hint),
            SimpleNamespace(rid="rA", day_hint=hint),
            SimpleNamespace(rid="rB", day_hint=hint),
        ],
        pins=(),
    )
    profile = SimpleNamespace(ride_minutes=60, last_mile_minutes=10, taxi_minutes=15)
    enriched = SimpleNamespace(
        snapshot=SimpleNamespace(candidates=cands, request=request),
        access_by_poi={REMOTE: profile},
    )
    m = cp_model.CpModel()
    presence = {(c, 1): m.NewBoolVar("p_%s" % c) for c in ("cR", "cA", "cB")}
    start = {(c, 1): m.NewIntVar(0, 1440, "s_%s" % c) for c in ("cR", "cA", "cB")}
    dur = {"cR": 180, "cA": 90, "cB": 90}
    bundle = SimpleNamespace(
        model=m, presence=presence, start=start, dur=dur, days=(1,),
        cap_escapes={}, active_ret_vars={}, dep_vars={},
    )
    add_c06_remote_exclusivity(bundle, enriched)
    for cid in ("cR", "cA", "cB"):
        m.Add(presence[(cid, 1)] == 1)
    return m, bundle


def test_c06_yields_when_user_wrote_days():
    m, bundle = _c06_world(with_day_hints=True)
    assert bundle.c06_yielded_to_day_plan is True
    assert cp_model.CpSolver().Solve(m) in (cp_model.FEASIBLE, cp_model.OPTIMAL)


def test_c06_still_applies_without_day_hints():
    """对照: 没写明天 → C-06 独占仍然生效(修复不是拆掉这条启发式)。"""
    m, bundle = _c06_world(with_day_hints=False)
    assert not getattr(bundle, "c06_yielded_to_day_plan", False)
    assert cp_model.CpSolver().Solve(m) == cp_model.INFEASIBLE


def test_has_user_day_blocks_ignores_out_of_range_hints():
    request = SimpleNamespace(
        days=2,
        musts=[
            SimpleNamespace(rid="r1", day_hint=2),
            SimpleNamespace(rid="r2", day_hint=9),
            SimpleNamespace(rid="r3", day_hint=None),
        ],
    )
    assert has_user_day_blocks(request) is True
    assert has_user_day_blocks(SimpleNamespace(days=2, musts=[
        SimpleNamespace(rid="r2", day_hint=9),
    ])) is False


# --- end-to-end snapshot ----------------------------------------------------
def _snapshot(*, with_day_hints: bool) -> FactSnapshot:
    hint = 1 if with_day_hints else None
    return FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=2,
            cities=("北京",),
            musts=(
                RequestedItem(
                    rid="rR", name="慕田峪长城", poi_id=REMOTE, day_hint=hint
                ),
                RequestedItem(
                    rid="rA", name="北京奥林匹克公园", poi_id=A, day_hint=hint
                ),
                RequestedItem(
                    rid="rB", name="鸟巢(国家体育场)", poi_id=B, day_hint=hint
                ),
            ),
        ),
        candidates=(
            CandidateItem(
                cid="cR", name="慕田峪长城", poi_id=REMOTE, kind="requested",
                rid="rR", category="sight", opening_hours="00:00-24:00",
                suggested_duration_min=180, remote=True,
            ),
            CandidateItem(
                cid="cA", name="北京奥林匹克公园", poi_id=A, kind="requested",
                rid="rA", category="sight", opening_hours="00:00-24:00",
                suggested_duration_min=90,
            ),
            CandidateItem(
                cid="cB", name="鸟巢(国家体育场)", poi_id=B, kind="requested",
                rid="rB", category="sight", opening_hours="00:00-24:00",
                suggested_duration_min=90,
            ),
        ),
        access_profiles=(
            AccessProfile(
                gateway="g", to_poi=REMOTE, ride_minutes=60, last_mile_minutes=10,
                departures=("08:30", "09:30"), returns=("14:30", "15:30"),
            ),
        ),
        source="synthetic",
    )


def test_all_written_musts_are_placed_and_disclosed():
    snap = _snapshot(with_day_hints=True)
    sol = solve_snapshot(enrich(snap), budget_s=10.0)
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    assert sol.objective_values.get("coverage") == 0, sol.objective_values
    assert sol.unplaced == [], sol.unplaced
    assert sol.c06_yielded_to_day_plan is True
    assert any("默认规则已让位" in line for line in render_disclosures(sol, snap))


def test_no_day_hints_keeps_c06_and_disclosure_silent():
    snap = _snapshot(with_day_hints=False)
    sol = solve_snapshot(enrich(snap), budget_s=10.0)
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    assert sol.c06_yielded_to_day_plan is False
    assert not any("默认规则已让位" in line for line in render_disclosures(sol, snap))


def test_disclosure_line_is_bilingual():
    sol = Solution(
        status="OPTIMAL",
        items=[SolutionItem(cid="cR", day=1, start_min=600, end_min=780)],
        c06_yielded_to_day_plan=True,
    )
    zh = render_disclosures(sol, SimpleNamespace(weather=()), lang="zh")
    en = render_disclosures(sol, SimpleNamespace(weather=()), lang="en")
    assert any("让位" in line for line in zh)
    assert any("yielded" in line for line in en)
