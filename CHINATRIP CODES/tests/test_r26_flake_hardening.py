# -*- coding: utf-8 -*-
"""R26 (2026-11-23 night) — load-flake root-cause regressions.

Flake A (shadow acceptance): `within_budget` used to be pure wall-clock
(`engine_ms <= budget_ms * 1.10`), so a loaded host flipped the whole-suite
acceptance gate red even though solve() is bounded by *deterministic* time
(`max_deterministic_time`) and the emitted plan is machine-independent.
The verdict is now deterministic: a solution whose search was NOT cut off by
the wall cap (``wall_capped=False``) counts as converged regardless of host
speed; only a genuinely wall-capped solve keeps the wall comparison
(R13g polluted-budget accounting).

Flake B (time_slot_integrity::test_plan_message_then_save_freezes_latest_plan)
is covered by that test itself now (explicit legacy path + stub retry fuel +
user-like resend before save).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.trip_solver.shadow.compare import EngineRun, _convergence


def _run(*, status="FEASIBLE", engine_ms=90000, budget_ms=3000, wall_capped=False):
    view = SimpleNamespace(
        status=status,
        wall_ms=engine_ms,
        engine_ms=engine_ms,
        budget_ms=budget_ms,
        wall_capped=wall_capped,
        unplaced=[],
        cards=[],
    )
    return EngineRun(view=view, signature="s", violations=[], results=[])


def test_deterministic_solve_is_not_red_from_wall_inflation():
    # Host 30x slower than budget, but the search finished under the
    # deterministic-time cap => converged (machine load is not an engine fact).
    conv = _convergence(
        _run(engine_ms=90000, budget_ms=3000, wall_capped=False), True, 3.0
    )
    assert conv["within_budget"] is True
    assert conv["wall_capped"] is False


def test_wall_capped_solve_keeps_wall_accounting():
    # Genuinely wall-cut solve far over tolerance => not converged (R13g).
    conv = _convergence(
        _run(engine_ms=90000, budget_ms=3000, wall_capped=True), True, 3.0
    )
    assert conv["within_budget"] is False
    # Wall-cut solve near the budget (cap fired at the budget edge) => passes.
    conv2 = _convergence(
        _run(engine_ms=3000, budget_ms=3000, wall_capped=True), True, 3.0
    )
    assert conv2["within_budget"] is True


def test_unknown_status_never_converges():
    conv = _convergence(_run(status="UNKNOWN", wall_capped=False), True, 3.0)
    assert conv["within_budget"] is False


def _report(name, *, within=True, polluted=False, status="OPTIMAL"):
    return {
        "scenario": name,
        "new": {
            "convergence": {
                "status": status,
                "wall_capped": polluted,
                "host_polluted": polluted,
                "engine_ms": 1000,
                "budget_ms": 3000,
                "within_budget": within,
            },
            "deterministic": True,
            "violation_counts": {},
        },
        "legacy": None,
        "plan_score_delta": {"within": True},
    }


def test_polluted_runs_excluded_from_convergence_denominator():
    # g11 shape under load: wall cap fires first => UNKNOWN + host_polluted.
    # It is a host fact, not an engine fact: excluded from the denominator.
    from app.services.trip_solver.shadow.metrics import acceptance_metrics

    reports = [_report("s%d" % i) for i in range(9)]
    reports.append(_report("g11", within=False, polluted=True, status="UNKNOWN"))
    conv = acceptance_metrics(reports)["gates"]["convergence_rate_new"]
    assert conv["pass"] is True
    assert conv["value"] == 1.0


def test_polluted_but_converged_run_never_inflates_the_ratio():
    # g11 shape: wall cap fired but the plan still met the budget tolerance
    # (within=True). Excluded from BOTH numerator and denominator, so the
    # reported convergence rate can never exceed 1.0.
    from app.services.trip_solver.shadow.metrics import acceptance_metrics

    reports = [_report("s%d" % i) for i in range(9)]
    reports.append(_report("g11", within=True, polluted=True, status="FEASIBLE"))
    conv = acceptance_metrics(reports)["gates"]["convergence_rate_new"]
    assert conv["pass"] is True
    assert conv["value"] == 1.0


def test_pollution_guard_blocks_an_unmeasurable_host():
    # 3/4 polluted > 20% guard: a host this slow cannot measure the engine,
    # the gate must fail loudly instead of hiding behind the exclusion.
    from app.services.trip_solver.shadow.metrics import acceptance_metrics

    reports = [_report("s1")]
    reports += [
        _report("p%d" % i, within=False, polluted=True, status="UNKNOWN")
        for i in range(3)
    ]
    conv = acceptance_metrics(reports)["gates"]["convergence_rate_new"]
    assert conv["pass"] is False


def test_unknown_without_wall_cap_still_fails_the_gate():
    # A genuine non-convergence (deterministic budget exhausted, no wall cap)
    # must stay red — the exclusion is strictly for host pollution.
    from app.services.trip_solver.shadow.metrics import acceptance_metrics

    reports = [_report("s%d" % i) for i in range(9)]
    reports.append(_report("g11", within=False, polluted=False, status="UNKNOWN"))
    conv = acceptance_metrics(reports)["gates"]["convergence_rate_new"]
    assert conv["pass"] is False
