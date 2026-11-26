"""P1-E tests: F-24 budget/hint, F-25 slack ladder, F-26 certificates,
F-41 determinism guard.

Real INFEASIBILITY in this model's design space is structural (pins vs
windows -- pins are never relaxed by F-25), so the ladder's end-to-end
rescue is covered through its mechanics (cumulative levels, model
shrinkage, disclosure rendering); the certificate is covered end-to-end
through pin-window and pin-pin clashes plus unplaced-reason attachment.
"""

from __future__ import annotations

from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.c01_c04 import build_model
from app.services.trip_solver.model.certificate import (
    classify_requested,
    emitted_codes,
    load_templates,
    render_reason,
)
from app.services.trip_solver.model.slack import (
    LADDER_STEP_NAMES,
    NEVER_RELAX,
    SlackFlags,
    ladder_levels,
    slack_disclosures,
)
from app.services.trip_solver.model.solve import (
    canonical_solution,
    determinism_guard,
    solve_snapshot,
)
from app.services.trip_solver.telemetry import solve_telemetry
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    FixedPin,
    RequestedItem,
    Solution,
    SolutionItem,
    TripRequest,
)


def cand(cid, name, hours, dur, *, rid=None, category="attraction"):
    return CandidateItem(
        cid=cid,
        name=name,
        kind="requested" if rid else "fill",
        rid=rid,
        category=category,
        opening_hours=hours,
        suggested_duration_min=dur,
    )


def req(rid, name, importance=3):
    return RequestedItem(rid=rid, name=name, importance=importance)


def snap(candidates, musts, *, days=1, pins=(), sight_cap=None):
    kwargs = {}
    if sight_cap is not None:
        kwargs["sight_cap_per_day"] = sight_cap
    return FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=days,
            cities=("北京",),
            musts=tuple(musts),
            pins=tuple(pins),
            **kwargs,
        ),
        candidates=tuple(candidates),
        source="synthetic",
    )


def mini():
    """2 musts + 1 fill on one day -- always solvable."""
    return snap(
        [
            cand("c1", "天坛", "08:00-18:00", 120, rid="r1"),
            cand("c2", "故宫", "08:30-17:00", 180, rid="r2"),
            cand("c3", " filler", "10:00-20:00", 60),
        ],
        [req("r1", "天坛"), req("r2", "故宫")],
    )


# ------------------------------------------------------------------ F-25


def test_ladder_levels_are_cumulative():
    levels = ladder_levels()
    assert len(levels) == len(LADDER_STEP_NAMES) + 1
    assert levels[0] == SlackFlags()
    for index, flags in enumerate(levels[1:], start=1):
        assert flags.level() == index
        for step in LADDER_STEP_NAMES[:index]:
            assert getattr(flags, step) is True
        for step in LADDER_STEP_NAMES[index:]:
            assert getattr(flags, step) is False


def test_never_relax_lists_the_hard_floor():
    joined = " ".join(NEVER_RELAX)
    for marker in ("C-01", "C-02", "C-04", "C-08", "F-20"):
        assert marker in joined


def test_relax_flags_change_the_model():
    enriched = enrich(mini())
    baseline = len(build_model(enriched).model.Proto().constraints)
    relaxed = len(
        build_model(
            enriched, SlackFlags(relax_diversity=True, relax_remote_exclusive=True)
        )
        .model.Proto()
        .constraints
    )
    dropped = len(
        build_model(enriched, SlackFlags(drop_fill=True)).model.Proto().constraints
    )
    assert relaxed < baseline  # C-06/C-16 groups skipped
    assert dropped > baseline  # fill-absence constraints added


def test_slack_disclosures_render_every_rung():
    flags = SlackFlags(
        drop_fill=True, relax_diversity=True, relax_remote_exclusive=True
    )
    lines = slack_disclosures(flags)
    assert lines == [
        render_reason(step, "zh", family="slack_reasons")
        for step in ("drop_fill", "relax_diversity", "relax_remote_exclusive")
    ]
    assert "远郊" in lines[-1]


# ------------------------------------------------------------------ F-26


def test_templates_cover_every_emitted_code():
    templates = load_templates()
    assert set(templates["certificate_reasons"]) == emitted_codes()
    assert set(templates["slack_reasons"]) == set(LADDER_STEP_NAMES)
    for family in ("certificate_reasons", "slack_reasons"):
        for code, entry in templates[family].items():
            assert entry.get("zh") and entry.get("en"), (family, code)
            assert render_reason(code, "zh", family=family, name="X")


def test_pin_window_infeasible_gets_certificate():
    snapshot = snap(
        [cand("c1", "升旗点", "09:00-17:00", 60, rid="r1")],
        [req("r1", "升旗点")],
        pins=(FixedPin(rid="r1", day=1, start_min=7 * 60),),
    )
    sol = solve_snapshot(enrich(snapshot))
    assert sol.status == "INFEASIBLE"
    assert sol.slack_level == 0  # no rung may rescue a pin clash
    assert sol.certificate, "certificate must explain the infeasibility"
    assert any(entry["code"] == "pin_conflict" for entry in sol.certificate)
    assert not sol.disclosures  # nothing was silently relaxed


def test_two_pins_same_slot_certificate():
    snapshot = snap(
        [
            cand("c1", "甲馆", "08:00-18:00", 60, rid="r1"),
            cand("c2", "乙馆", "08:00-18:00", 60, rid="r2"),
        ],
        [req("r1", "甲馆"), req("r2", "乙馆")],
        pins=(
            FixedPin(rid="r1", day=1, start_min=9 * 60),
            FixedPin(rid="r2", day=1, start_min=9 * 60),
        ),
    )
    sol = solve_snapshot(enrich(snapshot))
    assert sol.status == "INFEASIBLE"
    codes = {entry["code"] for entry in sol.certificate}
    assert "pin_conflict" in codes


def test_unplaced_reason_window_duration_conflict():
    snapshot = snap(
        [
            cand("c1", "天坛", "08:00-18:00", 120, rid="r1"),
            cand("c2", "颐和园", "09:00-10:30", 240, rid="r2"),
        ],
        [req("r1", "天坛"), req("r2", "颐和园")],
    )
    sol = solve_snapshot(enrich(snapshot))
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    unplaced = [u for u in sol.unplaced if u["rid"] == "r2"]
    assert unplaced, "120-min floor cannot fit a 90-min window"
    assert "window_duration_conflict" in unplaced[0]["reason_codes"]
    assert "最短游览时长" in unplaced[0]["reason"]


def test_unplaced_reason_day_capacity_conflict():
    snapshot = snap(
        [
            cand("c%d" % i, "景点%d" % i, "09:00-21:00", 200, rid="r%d" % i)
            for i in (1, 2, 3)
        ],
        [req("r1", "景点1"), req("r2", "景点2"), req("r3", "景点3")],
        sight_cap=2,
    )
    sol = solve_snapshot(enrich(snapshot))
    assert len(sol.unplaced) == 1  # sight cap 2/day over three musts
    entry = sol.unplaced[0]
    assert entry["reason_codes"]
    assert entry["reason"]


def test_classify_requested_directly():
    snapshot = snap(
        [cand("c1", "颐和园", "09:00-10:30", 240, rid="r1")],
        [req("r1", "颐和园")],
    )
    assert classify_requested(enrich(snapshot), "r1") == ["window_duration_conflict"]


# ------------------------------------------------------------------ F-24


def test_solve_without_hint_defaults():
    sol = solve_snapshot(enrich(mini()))
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    assert sol.hint_used is False
    assert sol.slack_level == 0
    assert sol.n_vars and sol.n_cons


def test_hint_is_used_and_deterministic():
    enriched = enrich(mini())
    base = solve_snapshot(enriched)
    hinted1 = solve_snapshot(enriched, hint=base)
    hinted2 = solve_snapshot(enriched, hint=base)
    assert hinted1.hint_used is True
    assert hinted1.status in ("OPTIMAL", "FEASIBLE")
    assert canonical_solution(hinted1) == canonical_solution(hinted2)


def test_hint_never_lowers_coverage():
    enriched = enrich(mini())
    base = solve_snapshot(enriched)
    hinted = solve_snapshot(enriched, hint=base)
    assert hinted.objective_values.get("coverage", 0) == base.objective_values.get(
        "coverage", 0
    )


# ------------------------------------------------------------------ F-41


def test_determinism_guard_true_on_mini():
    assert determinism_guard(mini()) is True


def test_canonical_ignores_wall_ms_only():
    def make(wall):
        return Solution(
            status="FEASIBLE",
            items=[SolutionItem(cid="c1", day=1, start_min=540, end_min=660)],
            wall_ms=wall,
        )

    assert canonical_solution(make(100)) == canonical_solution(make(999))


def test_determinism_guard_with_hint():
    enriched = enrich(mini())
    base = solve_snapshot(enriched)
    assert determinism_guard(mini(), hint=base) is True


# ------------------------------------------------------------------ F-36


def test_telemetry_reads_p1e_fields():
    snapshot = mini()
    sol = solve_snapshot(enrich(snapshot))
    record = solve_telemetry(snapshot, sol, engine="cpsat")
    assert record["n_vars"] > 0
    assert record["n_cons"] > 0
    assert record["slack_level"] == 0
    assert record["hint_used"] is False


# ------------------------------------------------- review round must-fix/S5


def test_early_pin_without_window_not_falsely_conflicted():
    """M1: pins before 08:30 with no window are valid (iron rule 19); the
    certificate must not invent a pin_conflict for them."""
    snapshot = snap(
        [
            cand("c1", "升旗占位", None, 60, rid="r1"),
            cand("c2", "甲馆", "08:00-18:00", 60, rid="r2"),
            cand("c3", "乙馆", "08:00-18:00", 60, rid="r3"),
        ],
        [req("r1", "升旗占位"), req("r2", "甲馆"), req("r3", "乙馆")],
        pins=(
            FixedPin(rid="r1", day=1, start_min=7 * 60),
            FixedPin(rid="r2", day=1, start_min=9 * 60),
            FixedPin(rid="r3", day=1, start_min=9 * 60),  # the real clash
        ),
    )
    sol = solve_snapshot(enrich(snapshot))
    assert sol.status == "INFEASIBLE"  # r2/r3 same-slot clash
    r1_codes = {e["code"] for e in sol.certificate if e.get("rid") == "r1"}
    assert "pin_conflict" not in r1_codes  # 07:00 pin is legal
    r23_codes = {e["code"] for e in sol.certificate if e.get("rid") in ("r2", "r3")}
    assert "pin_conflict" in r23_codes


def test_ladder_path_is_deterministic_too():
    """S5: byte-identity also on the INFEASIBLE -> ladder -> certificate
    path (two full runs, canonical comparison)."""
    snapshot = snap(
        [cand("c1", "升旗点", "09:00-17:00", 60, rid="r1")],
        [req("r1", "升旗点")],
        pins=(FixedPin(rid="r1", day=1, start_min=7 * 60),),
    )
    first = solve_snapshot(enrich(snapshot))
    second = solve_snapshot(enrich(snapshot))
    assert first.status == "INFEASIBLE"
    assert canonical_solution(first) == canonical_solution(second)
