"""Deterministic lexicographic solve + extraction (P1-D).

Each F-23 tier is solved in sequence under a fixed deterministic-work cap;
the overall wall-clock budget is only a safety envelope. A proven optimum is
fixed before the next tier starts; if a tier cannot prove optimality, the last
proven-optimal prefix is returned as FEASIBLE (or UNKNOWN when no prefix
exists). INFEASIBLE never falls back to sequencing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from ..types import Solution, SolutionItem
from .objectives import build_objectives

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot
    from .vars import VarBundle

SOLVER_SEED = 7
DEFAULT_BUDGET_SECONDS = 3.0
# Deterministic work cap per lexicographic tier. Wall-clock slices below are
# only a safety envelope; deterministic time decides how much search every
# run performs, so machine load cannot change the emitted plan.
TIER_DETERMINISTIC_BUDGET = 0.2


def solve(
    bundle: "VarBundle",
    enriched: "EnrichedSnapshot",
    budget_s: float = DEFAULT_BUDGET_SECONDS,
) -> Solution:
    started = time.perf_counter()
    tiers = build_objectives(bundle, enriched)
    solver = None
    status = "UNKNOWN"
    objective_values: dict[str, int] = {}
    fully_optimized = False

    for index, tier in enumerate(tiers):
        coverage_assumptions = index == 0 and bool(bundle.fill_gates)
        if coverage_assumptions:
            # Tier ① ignores fill variables. Solving that projection without
            # the optional-fill search space is mathematically identical (fills
            # cannot reduce unplaced requested items) and keeps trip-scale
            # corpora inside the Q3 budget.
            bundle.model.AddAssumptions(
                [gate.Not() for gate in bundle.fill_gates.values()]
            )
        candidate_solver = cp_model.CpSolver()
        candidate_solver.parameters.num_workers = 1
        candidate_solver.parameters.random_seed = SOLVER_SEED
        # The wall-clock cap is only a catastrophic safety net. Deterministic
        # time alone decides how much search each tier performs; do not gate
        # tiers on elapsed wall time, which would reintroduce load-dependent
        # output on slow machines.
        candidate_solver.parameters.max_time_in_seconds = budget_s
        candidate_solver.parameters.max_deterministic_time = TIER_DETERMINISTIC_BUDGET
        if tier.sense == "min":
            bundle.model.Minimize(tier.expression)
        else:
            bundle.model.Maximize(tier.expression)
        status_code = candidate_solver.Solve(bundle.model)
        status = candidate_solver.StatusName(status_code)
        if coverage_assumptions:
            bundle.model.ClearAssumptions()
        if status == "INFEASIBLE":
            return Solution(
                status="INFEASIBLE",
                wall_ms=int((time.perf_counter() - started) * 1000),
                objective_values=objective_values,
            )
        if status == "FEASIBLE":
            # A timeout may stop at an arbitrary feasible point. Accepting it
            # would make the emitted plan depend on machine load; keep the
            # last proven-optimal prefix instead (determinism red line).
            break
        if status != "OPTIMAL":
            # UNKNOWN / timeout / model-invalid is not infeasibility. Keep the
            # last proven-feasible lexicographic prefix and report honestly.
            break
        solver = candidate_solver
        best = int(round(candidate_solver.ObjectiveValue()))
        objective_values[tier.name] = best
        fully_optimized = status == "OPTIMAL" and index == len(tiers) - 1
        if index < len(tiers) - 1:
            bundle.model.Add(tier.expression == best)

    wall_ms = int((time.perf_counter() - started) * 1000)
    if solver is None:
        return Solution(
            status="UNKNOWN", wall_ms=wall_ms, objective_values=objective_values
        )

    items: list[SolutionItem] = []
    snapshot = enriched.snapshot
    for cid, day in bundle.cid_day_list:
        lit = bundle.presence[(cid, day)]
        if not solver.Value(lit):
            continue
        st = solver.Value(bundle.start[(cid, day)])
        du = solver.Value(bundle.dur[cid])
        items.append(
            SolutionItem(
                cid=cid,
                day=day,
                start_min=st,
                end_min=st + du,
                kind="visit",
                pinned=False,
                source="model",
            )
        )
    items.sort(key=lambda it: (it.day, it.start_min, it.cid))

    unplaced: list[dict] = []
    for req in list(snapshot.request.musts) + list(snapshot.request.wishes):
        lit = bundle.unplaced.get(req.rid)
        if lit is not None and solver.Value(lit):
            unplaced.append(
                {
                    "rid": req.rid,
                    "name": req.name,
                    "reason": "no-feasible-slot",
                    "note": "certificate detail lands with F-26 (P1-E)",
                }
            )

    from .c05_c08 import extract_access_legs
    from .c09_c16 import extract_hotel_anchors, extract_meal_anchors

    return Solution(
        status="OPTIMAL" if fully_optimized else "FEASIBLE",
        items=items,
        unplaced=unplaced,
        wall_ms=wall_ms,
        access_legs=extract_access_legs(bundle, enriched, solver),
        meal_anchors=extract_meal_anchors(bundle, enriched, solver),
        hotel_anchors=extract_hotel_anchors(bundle, enriched, solver),
        objective_values=objective_values,
    )


def solve_snapshot(
    enriched: "EnrichedSnapshot", budget_s: float = DEFAULT_BUDGET_SECONDS
) -> Solution:
    from .c01_c04 import build_model

    bundle = build_model(enriched)
    return solve(bundle, enriched, budget_s)
