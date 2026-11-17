"""P2-A shadow harness tests: corpus loading, view normalization, M7
assertion evaluators, B-class violation detectors (ground truth = the
incident's recorded defects), F-61 diff report and F-62 aggregate.

The legacy recording of G-01 IS the instrument's ground truth: the
documented defects (B-01 颐和园 silent drop, B-02 fill over unseated must,
B-03a 老舍茶馆 before the remote leg, B-03c card 12:38 ≠ leg 14:33) must be
detected, and the model engine must come back clean.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.shadow.asserts import AssertContext, evaluate
from app.services.trip_solver.shadow.compare import shadow_compare
from app.services.trip_solver.shadow.corpus import load_corpus, load_scenario
from app.services.trip_solver.shadow.metrics import acceptance_metrics
from app.services.trip_solver.shadow.violations import scan_violations, violation_counts
from app.services.trip_solver.shadow.views import (
    CardView,
    PlanView,
    signature,
    view_from_recording,
    view_from_solution,
)
from app.services.trip_solver.snapshot import default_golden_path, load_golden
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    FixedPin,
    RequestedItem,
    TripRequest,
)

G01 = default_golden_path()


# --- corpus (F-60) -----------------------------------------------------------


def test_corpus_v1_loads_four_scenarios():
    scenarios = load_corpus()
    names = [s.name for s in scenarios]
    assert "g01" in names
    for stem in ("g02_tower_late_gate", "g03_third_cluster", "g04_endpoint_transit"):
        assert stem in names, names
    assert len(scenarios) >= 4


def test_g01_has_recording_g02_g04_do_not():
    scenarios = {s.name: s for s in load_corpus()}
    assert scenarios["g01"].has_recording
    assert scenarios["g01"].legacy_raw["days"]
    for stem in ("g02_tower_late_gate", "g03_third_cluster", "g04_endpoint_transit"):
        assert not scenarios[stem].has_recording


def test_scenario_hash_is_stable():
    a = load_scenario(G01)
    b = load_scenario(G01)
    assert a.snapshot_hash == b.snapshot_hash
    assert len(a.snapshot_hash) == 64


# --- legacy view normalization + violation detectors (ground truth) ----------


def _legacy_view():
    scenario = load_scenario(G01)
    return view_from_recording(scenario.legacy_raw)


def test_legacy_view_keeps_untimed_requested_card():
    view = _legacy_view()
    yh = [c for c in view.by_name("颐和园") if c.day == 2]
    assert yh and not yh[0].timed and yh[0].requested is True


def test_legacy_violations_match_the_incident():
    scenario = load_scenario(G01)
    view = view_from_recording(scenario.legacy_raw)
    ctx = AssertContext(snapshot=scenario.snapshot)
    counts = violation_counts(scan_violations(view, ctx))
    # cpsat_as_is §4: B-01 silent drop + B-02 two fillers + B-03a 老舍茶馆
    # before the remote leg + B-03c card 12:38 vs leg 14:33
    assert counts == {"B-01": 1, "B-02": 2, "B-03a": 1, "B-03c": 1, "B-06": 0}


def test_legacy_b03c_evidence_names_the_mismatch():
    scenario = load_scenario(G01)
    view = view_from_recording(scenario.legacy_raw)
    ctx = AssertContext(snapshot=scenario.snapshot)
    v = [x for x in scan_violations(view, ctx) if x["bug"] == "B-03c"]
    assert v and "12:38" in v[0]["evidence"] and "14:33" in v[0]["evidence"]


# --- model view: the same scan must come back clean --------------------------


def _model_run(snapshot=None):
    snapshot, _, _ = load_golden(G01)
    if snapshot is not None:
        pass
    return snapshot


def test_model_view_clean_on_g01():
    scenario = load_scenario(G01)
    enriched = enrich(scenario.snapshot)
    sol = solve_snapshot(enriched)
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    view = view_from_solution(sol, scenario.snapshot)
    ctx = AssertContext(snapshot=scenario.snapshot, enriched=enriched)
    counts = violation_counts(scan_violations(view, ctx))
    assert counts == {"B-01": 0, "B-02": 0, "B-03a": 0, "B-03c": 0, "B-06": 0}
    # an untimed requested card cannot exist in the solution type (B-01 class)
    assert all(c.timed for c in view.cards)


def test_model_solutions_are_byte_identical_on_g01():
    scenario = load_scenario(G01)
    sigs = []
    for _ in range(2):
        enriched = enrich(scenario.snapshot)
        sol = solve_snapshot(enriched)
        sigs.append(signature(view_from_solution(sol, scenario.snapshot)))
    assert sigs[0] == sigs[1]


# --- assertion evaluators (M7) ------------------------------------------------


def _mini_snapshot(with_pin=False):
    must = RequestedItem(rid="r1", name="故宫博物院", poi_id="p1")
    tower = CandidateItem(
        cid="c2",
        name="上海中心大厦上海之巅观光厅",
        poi_id="p2",
        kind="fill",
        category="sight",
        opening_hours="08:30-22:00",
        suggested_duration_min=90,
    )
    request = TripRequest(
        days=1,
        cities=("上海",),
        musts=(must,),
        pins=(FixedPin(rid="r1", day=1, start_min=430),) if with_pin else (),
    )
    return FactSnapshot(
        schema_version=1,
        request=request,
        candidates=(
            CandidateItem(
                cid="c1",
                name="故宫博物院",
                poi_id="p1",
                kind="requested",
                rid="r1",
                category="museum",
                opening_hours="08:30-17:00",
                suggested_duration_min=120,
            ),
            tower,
        ),
    )


def test_time_range_requires_pin_skips_without_pin():
    snapshot = _mini_snapshot(with_pin=False)
    view = PlanView(engine="cpsat")
    res = evaluate(
        {"type": "time_range", "args": {"day": 1, "name": "故宫博物院", "start": "07:00", "end": "08:45", "requires_pin": "天安门广场"}},
        view,
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "skipped"


def test_time_range_passes_with_pin_set():
    snapshot = _mini_snapshot(with_pin=True)
    view = PlanView(engine="cpsat", cards=[CardView(name="故宫博物院", day=1, start="07:10", end="08:40")])
    res = evaluate(
        {"type": "time_range", "args": {"day": 1, "name": "故宫博物院", "start": "07:00", "end": "08:45", "requires_pin": "故宫博物院"}},
        view,
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "pass"


def test_time_range_fails_outside_window():
    snapshot = _mini_snapshot(with_pin=True)
    view = PlanView(engine="cpsat", cards=[CardView(name="故宫博物院", day=1, start="09:30", end="11:00")])
    res = evaluate(
        {"type": "time_range", "args": {"day": 1, "name": "故宫博物院", "start": "07:00", "end": "08:45", "requires_pin": "故宫博物院"}},
        view,
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "fail" and "09:30" in res["detail"]


def test_sequence_skips_absent_card_fails_wrong_order():
    snapshot = _mini_snapshot()
    empty = PlanView(engine="cpsat")
    res = evaluate(
        {"type": "sequence", "args": {"day": 1, "order": ["甲", "乙"]}},
        empty,
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "skipped"

    cards = [
        CardView(name="甲", day=1, start="14:00", end="15:00", requested=True),
        CardView(name="乙", day=1, start="09:00", end="10:00", requested=True),
    ]
    res = evaluate(
        {"type": "sequence", "args": {"day": 1, "order": ["甲", "乙"]}},
        PlanView(engine="cpsat", cards=cards),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "fail"


def test_no_unrequested_before_detects_filler_and_skips_absent_anchor():
    snapshot = _mini_snapshot()
    cards = [
        CardView(name="老舍茶馆", day=1, start="09:10", end="10:10", requested=False),
        CardView(name="慕田峪长城", day=1, start="12:38", end="15:38", requested=True, remote=True),
    ]
    res = evaluate(
        {"type": "no_unrequested_before", "args": {"day": 1, "before": "慕田峪长城"}},
        PlanView(engine="cpsat", cards=cards),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "fail" and "老舍茶馆" in res["detail"]

    res = evaluate(
        {"type": "no_unrequested_before", "args": {"day": 2, "before": "慕田峪长城"}},
        PlanView(engine="cpsat", cards=cards),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "skipped"


def test_same_venue_pending_without_meal_cards_fails_wrong_anchor():
    snapshot = _mini_snapshot()
    res = evaluate(
        {"type": "same_venue", "args": {"day": 1, "meal": "lunch", "name": "慕田峪长城"}},
        PlanView(engine="cpsat"),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "pending"  # meal assembly lands in P1-F

    meal = CardView(name="午饭", day=1, start="11:38", end="12:38", kind="meal", anchor="老舍茶馆")
    res = evaluate(
        {"type": "same_venue", "args": {"day": 1, "meal": "lunch", "name": "慕田峪长城"}},
        PlanView(engine="legacy", cards=[meal]),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "fail" and "老舍茶馆" in res["detail"]


def test_requested_coverage_fail_and_pass():
    snapshot = _mini_snapshot()
    # present but untimed = the B-01 shape
    card = CardView(name="故宫博物院", day=1, start=None, requested=True)
    res = evaluate(
        {"type": "requested_coverage", "args": {}},
        PlanView(engine="legacy", cards=[card]),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "fail" and "B-01" in res["detail"]
    # timed = pass
    card = CardView(name="故宫博物院", day=1, start="09:00", end="11:00", requested=True)
    res = evaluate(
        {"type": "requested_coverage", "args": {}},
        PlanView(engine="legacy", cards=[card]),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "pass"
    # absent but disclosed-unplaced = pass
    res = evaluate(
        {"type": "requested_coverage", "args": {}},
        PlanView(engine="legacy", unplaced=[{"rid": "r1", "name": "故宫博物院"}]),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "pass"


def test_no_entry_cap_breach_breach_and_skip():
    snapshot = _mini_snapshot()
    enriched = enrich(snapshot)
    cap, reason = enriched.caps["c2"]
    assert cap == 930 and reason == "big-site"  # tower capped at 15:30

    breacher = CardView(
        name="上海中心大厦上海之巅观光厅", day=1, start="19:00", end="20:30", requested=False, cid="c2"
    )
    res = evaluate(
        {"type": "no_entry_cap_breach", "args": {"caps": {"generic": "16:30", "big": "15:30"}}},
        PlanView(engine="cpsat", cards=[breacher]),
        AssertContext(snapshot=snapshot, enriched=enriched),
    )
    assert res["status"] == "fail" and "19:00" in res["detail"]

    # legacy cards without cap data → skipped (no heuristics)
    res = evaluate(
        {"type": "no_entry_cap_breach", "args": {"caps": {"generic": "16:30"}}},
        PlanView(engine="legacy", cards=[CardView(name="某塔", day=1, start="19:00")]),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "skipped"


def test_day_floor_ceiling_assertions():
    snapshot = _mini_snapshot()
    cards = [CardView(name="甲", day=1, start="12:08", end="14:40", requested=True)]
    res = evaluate(
        {"type": "day_start_floor", "args": {"day": 1, "not_before": "11:30"}},
        PlanView(engine="cpsat", cards=cards),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "pass"
    res = evaluate(
        {"type": "day_end_ceiling", "args": {"day": 1, "not_after": "17:30"}},
        PlanView(engine="cpsat", cards=cards),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "pass"
    late = [CardView(name="甲", day=1, start="18:00", end="19:00", requested=True)]
    res = evaluate(
        {"type": "day_end_ceiling", "args": {"day": 1, "not_after": "17:30"}},
        PlanView(engine="cpsat", cards=late),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "fail"


def test_unknown_assertion_type_fails_loud():
    snapshot = _mini_snapshot()
    res = evaluate(
        {"type": "time_rangee", "args": {}},
        PlanView(engine="cpsat"),
        AssertContext(snapshot=snapshot),
    )
    assert res["status"] == "fail" and "unknown" in res["detail"]


# --- F-61 diff report + F-62 aggregate ----------------------------------------


def test_shadow_compare_g01_full_shape():
    scenario = load_scenario(G01)
    report = shadow_compare(scenario)
    assert report["new"]["status"] in ("OPTIMAL", "FEASIBLE")
    assert report["new"]["deterministic"] is True
    det = [r for r in report["new"]["assertions"] if r["type"] == "deterministic"]
    assert det and det[0]["status"] == "pass"
    assert report["new"]["convergence"]["within_budget"] is True
    assert report["new"]["violation_counts"] == {
        "B-01": 0, "B-02": 0, "B-03a": 0, "B-03c": 0, "B-06": 0
    }
    # legacy side detects the incident, model is not-worse everywhere
    assert report["legacy"]["violation_counts"]["B-01"] == 1
    assert report["not_worse"]["pass"] is True
    legacy_det = [r for r in report["legacy"]["assertions"] if r["type"] == "deterministic"]
    assert legacy_det and legacy_det[0]["status"] == "skipped"


def test_shadow_compare_scenario_without_recording():
    scenario = load_scenario(G01)
    scenarios = {s.name: s for s in load_corpus()}
    report = shadow_compare(scenarios["g02_tower_late_gate"])
    assert report["legacy"] is None and report["not_worse"] is None
    assert report["new"]["assertion_counts"]["fail"] == 0


def test_acceptance_metrics_verdict_and_gates():
    scenarios = load_corpus()
    reports = [shadow_compare(s) for s in scenarios]
    metrics = acceptance_metrics(reports)
    assert metrics["corpus"] == [s.name for s in scenarios]
    assert metrics["new_violations_total"] == {
        "B-01": 0, "B-02": 0, "B-03a": 0, "B-03c": 0, "B-06": 0
    }
    assert metrics["legacy_violations_total"]["B-01"] == 1
    gates = metrics["gates"]
    assert gates["corpus_size"]["pass"] is False  # 4 < 12 until P2-B
    assert gates["violation_classes_zero_new"]["pass"] is True
    assert gates["convergence_rate_new"]["pass"] is True
    assert gates["determinism_rate"]["pass"] is True
    assert gates["not_worse_vs_recording"]["pass"] is True
    assert gates["plan_score_delta"]["pass"] is None  # pending P1-D/P1-F
    assert metrics["verdict"]["mode"] == "shadow-instrument (P2-A)"
    assert metrics["verdict"]["switch_ready"] is False
