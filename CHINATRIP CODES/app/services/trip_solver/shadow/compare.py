"""F-61 shadow_compare — old (recorded) vs new (model) on the same snapshot.

Offline batch only (audit M6): the harness replays committed corpus
snapshots through the model engine twice (determinism), evaluates the
scenario's M7 assertions against both the recorded legacy run and the
model run, scans both for B-class violations, and emits one report dict
per scenario. In-request double-compute is explicitly NOT part of P2-A
(the optional live sampling flag belongs to the P3 entry adapter).

Relative criteria (F-61/F-62): the legacy engine is NOT required to be
perfect — the report measures "not worse", violation classes, and
convergence. Pre-P1-F the model legitimately pends meal/disclosure
assertions; the report shows that honestly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from ..inputs.enrich import enrich
from ..model.solve import solve_snapshot
from .asserts import AssertContext, evaluate
from .corpus import Scenario
from .score import delta_pct, score_plan, within_threshold
from .views import signature, view_from_recording, view_from_solution
from .violations import scan_violations, violation_counts

DEFAULT_BUDGET_S = 3.0
NO_SOLUTION_DISCLOSURE = "求解器未收敛"


@dataclass
class EngineRun:
    view: Any  # PlanView
    signature: str
    violations: list[dict]
    results: list[dict]
    score: Any = None  # F-61 plan_score over the materialised plan (int|None)


def _run_model(
    scenario: Scenario, budget_s: float
) -> tuple[EngineRun, EngineRun, bool]:
    """Solve twice on the same snapshot (F-41 instrument-level determinism)."""
    runs: list[EngineRun] = []
    for _ in range(2):
        started = time.perf_counter()
        enriched = enrich(scenario.snapshot)
        sol = solve_snapshot(enriched, budget_s=budget_s)
        wall_ms = int((time.perf_counter() - started) * 1000)
        sol.wall_ms = wall_ms
        view = view_from_solution(sol, scenario.snapshot)
        # Q3 披露放宽：收敛按引擎实际预算判定（budget_used_ms>传入值
        # 即发生过 disclosed raise）
        view.budget_ms = getattr(sol, "budget_used_ms", None) or int(budget_s * 1000)
        ctx = AssertContext(snapshot=scenario.snapshot, enriched=enriched)
        run_score = None
        try:  # F-30 materialise → SAME legacy scorer as the replay side
            from ..assembly.materialize import materialize_plan

            run_score = score_plan(
                materialize_plan(sol, scenario.snapshot), scenario.snapshot
            )
        except Exception:
            run_score = None  # unscored shows as a gap, never a fake number
        runs.append(
            EngineRun(
                view=view,
                signature=signature(view),
                violations=scan_violations(view, ctx),
                results=[evaluate(a, view, ctx) for a in scenario.expect],
                score=run_score,
            )
        )
    deterministic = runs[0].signature == runs[1].signature
    # `deterministic` is a runner-level assertion: patch the per-view result
    # with the actual two-run signature comparison (F-41 instrument).
    for run in runs:
        for res in run.results:
            if res["type"] == "deterministic":
                res.update(
                    status="pass" if deterministic else "fail",
                    detail="two solves byte-identical (F-41)"
                    if deterministic
                    else "runs diverged — determinism broken",
                )
    return runs[0], runs[1], deterministic


def _run_legacy(scenario: Scenario) -> Optional[EngineRun]:
    if not scenario.legacy_raw:
        return None
    view = view_from_recording(scenario.legacy_raw)
    ctx = AssertContext(snapshot=scenario.snapshot, enriched=None)
    results = [evaluate(a, view, ctx) for a in scenario.expect]
    # P2-B: in-process replay recordings carry their own two-run
    # calibration in provenance; hand recordings stay skipped — never
    # fake a verdict either way
    prov = scenario.legacy_raw.get("provenance") or {}
    kind = scenario.legacy_raw.get("kind") or prov.get("kind")
    calibrated = (
        prov.get("determinism")
        if kind == "in-process-replay" and "determinism" in prov
        else None
    )
    for res in results:
        if res["type"] == "deterministic":
            if calibrated is None:
                res.update(
                    status="skipped",
                    detail="runner-level check: legacy determinism needs ≥ 2 "
                    "recordings of the same request (P2-B calibration)",
                )
            elif calibrated:
                res.update(
                    status="pass",
                    detail="two in-process replays byte-identical (P2-B calibration)",
                )
            else:
                res.update(
                    status="fail",
                    detail="in-process replays diverged — legacy engine is "
                    "non-deterministic on this snapshot",
                )
    return EngineRun(
        view=view,
        signature=signature(view),
        violations=scan_violations(view, ctx),
        results=results,
    )


def _convergence(runs: EngineRun, deterministic: bool, budget_s: float) -> dict:
    view = runs.view
    wall_ms = getattr(view, "wall_ms", None) or 0
    status = view.status or "unknown"
    budget_ms = getattr(view, "budget_ms", None) or int(budget_s * 1000)
    return {
        "status": status,
        "wall_ms": wall_ms,
        "budget_ms": budget_ms,
        "within_budget": wall_ms <= budget_ms and status in ("OPTIMAL", "FEASIBLE"),
        "deterministic": deterministic,
        "unplaced_count": len(view.unplaced),
        "fill_count": sum(1 for c in view.cards if c.requested is False and c.timed),
    }


def _legacy_convergence(scenario: Scenario) -> dict:
    lines = list((scenario.legacy_raw or {}).get("disclosures", ()) or [])
    return {
        "recorded": scenario.has_recording,
        "no_solution_disclosures": sum(
            1 for line in lines if NO_SOLUTION_DISCLOSURE in str(line)
        ),
        "disclosures": len(lines),
    }


def shadow_compare(scenario: Scenario, budget_s: float = DEFAULT_BUDGET_S) -> dict:
    """Full per-scenario diff report (F-61)."""
    first, _second, deterministic = _run_model(scenario, budget_s)
    legacy = _run_legacy(scenario)

    report: dict[str, Any] = {
        "scenario": scenario.name,
        "snapshot_hash": scenario.snapshot_hash,
        "provenance": scenario.provenance,
        "assertion_types": [a.get("type") for a in scenario.expect],
        "new": {
            "status": first.view.status,
            "wall_ms": first.view.wall_ms,
            "deterministic": deterministic,
            "assertions": first.results,
            "violations": first.violations,
            "violation_counts": violation_counts(first.violations),
            "assertion_counts": _count_assertions(first.results),
            "convergence": _convergence(first, deterministic, budget_s),
            "plan_score": first.score,
        },
        "legacy": None,
        "not_worse": None,  # filled below when a recording exists
    }

    if legacy is not None:
        legacy_block = {
            "source": scenario.legacy_path,
            # top-level kind (provenance fallback; P2-A hand recordings
            # and P2-B replay recordings both carry the top-level field)
            "kind": scenario.legacy_raw.get("kind")
            or (scenario.legacy_raw.get("provenance") or {}).get("kind")
            or "recorded-actual-output",
            "determinism": (scenario.legacy_raw.get("provenance") or {}).get(
                "determinism"
            ),
            "assertions": legacy.results,
            "violations": legacy.violations,
            "violation_counts": violation_counts(legacy.violations),
            "assertion_counts": _count_assertions(legacy.results),
            "convergence": _legacy_convergence(scenario),
            "plan_score": (scenario.legacy_raw.get("provenance") or {}).get(
                "plan_score"
            ),
        }
        report["legacy"] = legacy_block
        report["not_worse"] = _not_worse(
            violation_counts(legacy.violations), report["new"]["violation_counts"]
        )
        # F-62 companion criterion: plan-score Δ ≥ −2% vs the legacy run
        legacy_score = legacy_block["plan_score"]
        model_score = report["new"]["plan_score"]
        report["plan_score_delta"] = {
            "legacy": legacy_score,
            "model": model_score,
            "delta_pct": delta_pct(model_score, legacy_score),
            "threshold_pct": -2.0,
            "within": within_threshold(model_score, legacy_score),
        }
    return report


def _count_assertions(results: list[dict]) -> dict:
    counts = {"pass": 0, "fail": 0, "pending": 0, "skipped": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def _not_worse(legacy_counts: dict, new_counts: dict) -> dict:
    """Relative criterion per F-62/M9: the model may not have more
    violations in any tracked class than the legacy recording."""
    per_class = {
        cls: new_counts.get(cls, 0) <= legacy_counts.get(cls, 0)
        for cls in ("B-01", "B-02", "B-03a", "B-03c", "B-06")
    }
    return {
        "per_class": per_class,
        "pass": all(per_class.values()),
    }
