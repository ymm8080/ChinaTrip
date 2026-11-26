# -*- coding: utf-8 -*-
"""R36 (2026-11-24): the cap-escape boolean gets ONE stable meaning.

Contract (C-02 docstring, since R12-H22): ``cap_escapes`` is created by
C-02 and constrained by C-06 — esc ⇒ a remote is present that day,
esc ⇒ the after-return branch, esc ⇒ at most one escape card per day,
and on days without a remote esc is pinned to 0.

Three disease faces of the old implementation (all from putting the
bindings inside C-06's per-remote loop, or skipping them wholesale):

1. over-constrained (>=2 profiled remotes): ``esc => presence(r,d)`` was
   emitted once PER remote, i.e. esc ⇒ EVERY remote present that day.
   Two remotes can never both run the same day (chain + day budget), so
   the escape slot was dead on every remote-return day — the mirrored
   "dropped must" shape, solver-side. Typical Beijing request
   (慕田峪 + 八达岭 + 鸟巢) hits this.
2. under-constrained (R31 yield): when the user wrote a day plan, C-06
   returned before any binding → esc free → the cap gate was wholly
   bypassed (documented by R35; the outbound ``enforce_entry_gate``
   patched the symptom downstream only).
3. under-constrained (no profiled remotes at all): early return → esc
   free, violating the same C-02 contract line.

Fix shape: a per-day aggregate ``remote_day[d] = OR(presence[r,d])``
built once outside the remote loop; ``(esc ∧ presence[r,d]) ⇒ aft_r``
for the actually-present remote; yield branch keeps a minimal anchor
(existence + <=1 per day) — NOT the quota anchors that made the R35
bisection PROVEN INFEASIBLE.
"""

from __future__ import annotations

from types import SimpleNamespace

from ortools.sat.python import cp_model

from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.c05_c08 import add_c06_remote_exclusivity
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.types import (
    AccessProfile,
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TripRequest,
)

FLEX = 30
CAP_M = 16 * 60 + 30  # generic entry cap 990
CAP_LATE = 17 * 60 + 30  # 1050 — past cap + flex, only escapable
RET_MIN = 14 * 60 + 30  # 870 return bus
BACK_MIN = 70  # ride 60 + last mile 10


def _c02_gate(m, presence, start, esc, cid, day):
    """Mirror C-02's gate for cid/day: start <= cap+flex unless esc."""
    m.Add(start[(cid, day)] <= CAP_M + FLEX).OnlyEnforceIf(
        [presence[(cid, day)], esc.Not()]
    )


def _world(
    *,
    remotes=("cM", "cB"),
    remote_days=None,
    capped=("cX",),
    capped_days=None,
    with_day_hints=False,
    ret_pins=None,
):
    """Unit world for add_c06_remote_exclusivity.

    remotes: cids carrying access profiles. capped: cids with an entry
    cap (esc booleans created). remote_days/capped_days pin which day
    each card is present on (1-based, mirrors C-08-created chain vars).
    """
    remote_days = remote_days or {"cM": 1, "cB": 2}
    capped_days = capped_days or {"cX": (1, 2)}
    ret_pins = ret_pins or {("cM", 1): RET_MIN}
    m = cp_model.CpModel()
    days = (1, 2)
    cids = tuple(remotes) + tuple(capped)
    presence, start = {}, {}
    for d in days:
        for c in cids:
            presence[(c, d)] = m.NewBoolVar("p_%s_%d" % (c, d))
            start[(c, d)] = m.NewIntVar(0, 1440, "s_%s_%d" % (c, d))
    dur = {c: (180 if c in remotes else 60) for c in cids}
    cap_escapes = {}
    for c in capped:
        for d in capped_days.get(c, ()):
            cap_escapes[(c, d)] = m.NewBoolVar("capes_%s_%d" % (c, d))

    profile = SimpleNamespace(ride_minutes=60, last_mile_minutes=10, taxi_minutes=15)
    enriched = SimpleNamespace(
        snapshot=SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    cid=c,
                    rid="r_" + c,
                    poi_id="poi_" + c,
                    category="sight",
                    suggested_duration_min=dur[c],
                )
                for c in cids
            ],
            request=SimpleNamespace(
                days=2,
                musts=[
                    SimpleNamespace(
                        rid="r_" + c,
                        day_hint=(1 if with_day_hints else None),
                    )
                    for c in cids
                ],
                pins=(),
            ),
        ),
        access_by_poi={"poi_" + c: profile for c in remotes},
    )

    bundle = SimpleNamespace(
        model=m,
        presence=presence,
        start=start,
        dur=dur,
        days=days,
        cap_escapes=cap_escapes,
        active_ret_vars={},
        dep_vars={},
    )
    # remote chain vars (C-08 normally creates these before C-06)
    for rid_cid in remotes:
        for d in days:
            if (rid_cid, d) in ret_pins:
                ret = m.NewIntVar(0, 1440, "ret_%s_%d" % (rid_cid, d))
                m.Add(ret == ret_pins[(rid_cid, d)])
                bundle.active_ret_vars[(rid_cid, d)] = ret
                dep = m.NewIntVar(0, 1440, "dep_%s_%d" % (rid_cid, d))
                bundle.dep_vars[(rid_cid, d)] = dep

    add_c06_remote_exclusivity(bundle, enriched)

    for c in remotes:
        for d in days:
            m.Add(presence[(c, d)] == (1 if remote_days.get(c) == d else 0))
    for c in capped:
        for d in capped_days.get(c, ()):
            m.Add(presence[(c, d)] == 1)
    return m, bundle, presence, start, cap_escapes


def _solve(m):
    solver = cp_model.CpSolver()
    status = solver.Solve(m)
    return solver, status


def test_escape_slot_alive_with_two_remotes():
    """慕田峪 day1 + 八达岭 day2 + capped 鸟巢 late on day1 → esc lives.

    Old code: esc(cX,1) ⇒ presence(cB,1)=0 → esc dead → INFEASIBLE.
    New code: esc ⇒ OR(presence) → 慕田峪在场 day1 suffices; esc also
    forces the after-return branch (start ≥ ret + ride + last mile).
    """
    m, bundle, presence, start, cap_escapes = _world()
    _c02_gate(m, presence, start, cap_escapes[("cX", 1)], "cX", 1)
    m.Add(start[("cX", 1)] >= CAP_LATE)  # 17:30 — must ride the escape
    solver, status = _solve(m)
    assert status in (cp_model.FEASIBLE, cp_model.OPTIMAL), status
    assert solver.Value(cap_escapes[("cX", 1)]) == 1
    assert solver.Value(start[("cX", 1)]) >= RET_MIN + BACK_MIN


def test_escape_needs_a_remote_that_day():
    """esc=1 with no remote present that day stays impossible."""
    m, bundle, presence, start, cap_escapes = _world(remote_days={"cM": 2, "cB": 2})
    _c02_gate(m, presence, start, cap_escapes[("cX", 1)], "cX", 1)
    m.Add(start[("cX", 1)] >= CAP_LATE)
    solver, status = _solve(m)
    assert status == cp_model.INFEASIBLE


def test_no_remote_at_all_pins_escape_zero():
    """C-02 contract: days without any remote pin esc to 0 (gate holds)."""
    m, bundle, presence, start, cap_escapes = _world(remotes=())
    _c02_gate(m, presence, start, cap_escapes[("cX", 1)], "cX", 1)
    m.Add(start[("cX", 1)] >= CAP_LATE)
    solver, status = _solve(m)
    assert status == cp_model.INFEASIBLE

    # and a normal in-cap placement keeps esc at 0
    m2, _b2, presence2, start2, cap_escapes2 = _world(remotes=())
    _c02_gate(m2, presence2, start2, cap_escapes2[("cX", 1)], "cX", 1)
    m2.Add(start2[("cX", 1)] == 15 * 60)
    solver2, status2 = _solve(m2)
    assert status2 in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    assert solver2.Value(cap_escapes2[("cX", 1)]) == 0


def test_yield_mode_escape_still_needs_remote_day():
    """R31 yield keeps a minimal anchor: esc ⇒ some remote that day."""
    m, bundle, presence, start, cap_escapes = _world(
        remote_days={"cM": 2, "cB": 2}, with_day_hints=True
    )
    assert bundle.c06_yielded_to_day_plan is True
    _c02_gate(m, presence, start, cap_escapes[("cX", 1)], "cX", 1)
    m.Add(start[("cX", 1)] >= CAP_LATE)
    solver, status = _solve(m)
    # old code: C-06 skipped entirely, esc free → FEASIBLE (gate void).
    assert status == cp_model.INFEASIBLE


def test_yield_mode_escape_works_on_remote_day():
    m, bundle, presence, start, cap_escapes = _world(with_day_hints=True)
    assert bundle.c06_yielded_to_day_plan is True
    _c02_gate(m, presence, start, cap_escapes[("cX", 1)], "cX", 1)
    m.Add(start[("cX", 1)] >= CAP_LATE)
    solver, status = _solve(m)
    assert status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    assert solver.Value(cap_escapes[("cX", 1)]) == 1


def test_yield_mode_at_most_one_escape_card_per_day():
    """The <=1-slot half of the minimal anchor (old code: both escape)."""
    m, bundle, presence, start, cap_escapes = _world(
        capped=("cX", "cY"),
        capped_days={"cX": (1,), "cY": (1, 2)},
        with_day_hints=True,
    )
    assert bundle.c06_yielded_to_day_plan is True
    for c in ("cX", "cY"):
        _c02_gate(m, presence, start, cap_escapes[(c, 1)], c, 1)
        m.Add(start[(c, 1)] >= CAP_LATE)
    solver, status = _solve(m)
    assert status == cp_model.INFEASIBLE


# --- end-to-end: the typical Beijing request must stay feasible -------
def _snapshot_two_remotes() -> FactSnapshot:
    return FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=3,
            cities=("北京",),
            musts=(
                RequestedItem(rid="rM", name="慕田峪长城", poi_id="poi_mtu"),
                RequestedItem(rid="rB", name="八达岭长城", poi_id="poi_bdl"),
                RequestedItem(rid="rX", name="鸟巢(国家体育场)", poi_id="poi_nest"),
            ),
        ),
        candidates=(
            CandidateItem(
                cid="cM",
                name="慕田峪长城",
                poi_id="poi_mtu",
                kind="requested",
                rid="rM",
                category="sight",
                opening_hours="00:00-24:00",
                suggested_duration_min=180,
                remote=True,
            ),
            CandidateItem(
                cid="cB",
                name="八达岭长城",
                poi_id="poi_bdl",
                kind="requested",
                rid="rB",
                category="sight",
                opening_hours="00:00-24:00",
                suggested_duration_min=180,
                remote=True,
            ),
            CandidateItem(
                cid="cX",
                name="鸟巢(国家体育场)",
                poi_id="poi_nest",
                kind="requested",
                rid="rX",
                category="sight",
                opening_hours="08:00-21:00",
                suggested_duration_min=60,
            ),
        ),
        access_profiles=(
            AccessProfile(
                gateway="g_mtu",
                to_poi="poi_mtu",
                ride_minutes=60,
                last_mile_minutes=10,
                departures=("08:30", "09:30"),
                returns=("14:30", "15:30"),
            ),
            AccessProfile(
                gateway="g_bdl",
                to_poi="poi_bdl",
                ride_minutes=70,
                last_mile_minutes=15,
                departures=("08:30", "09:30"),
                returns=("14:30", "15:30"),
            ),
        ),
        source="synthetic",
    )


def test_two_remote_request_keeps_full_coverage():
    """Regression guard: the multi-remote request stays feasible with
    full must coverage, and the capped card never opens past cap+flex
    unless a remote is present on its day (escape semantics, not a
    void gate)."""
    snap = _snapshot_two_remotes()
    sol = solve_snapshot(enrich(snap), budget_s=15.0)
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    assert sol.objective_values.get("coverage") == 0, sol.objective_values
    assert sol.unplaced == [], sol.unplaced
    assert sol.c06_yielded_to_day_plan is False
    placed = {i.cid: i for i in sol.items}
    assert {"cM", "cB", "cX"} <= set(placed)
    remote_days = {placed[cid].day for cid in ("cM", "cB")}
    nest = placed["cX"]
    assert nest.start_min <= CAP_M + FLEX or nest.day in remote_days
