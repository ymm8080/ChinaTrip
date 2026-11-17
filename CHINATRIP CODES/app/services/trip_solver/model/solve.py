"""Deterministic solve + extraction (P1-C1 minimal; F-24 budget/slack/
certificates are P1-E).

num_workers=1 + fixed seed → same snapshot, byte-identical plan (F-41
red line). INFEASIBLE is a terminal answer with an empty plan — never a
sequential fallback.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from ..types import Solution, SolutionItem

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot
    from .vars import VarBundle

SOLVER_SEED = 7
DEFAULT_BUDGET_SECONDS = 3.0


def solve(
    bundle: "VarBundle",
    enriched: "EnrichedSnapshot",
    budget_s: float = DEFAULT_BUDGET_SECONDS,
) -> Solution:
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = SOLVER_SEED
    solver.parameters.max_time_in_seconds = budget_s
    started = time.perf_counter()
    status_code = solver.Solve(bundle.model)
    wall_ms = int((time.perf_counter() - started) * 1000)
    status = solver.StatusName(status_code)

    if status not in ("OPTIMAL", "FEASIBLE"):
        return Solution(status="INFEASIBLE", wall_ms=wall_ms)

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
    items.sort(key=lambda it: (it.day, it.start_min))

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

    return Solution(
        status="OPTIMAL" if status == "OPTIMAL" else "FEASIBLE",
        items=items,
        unplaced=unplaced,
        wall_ms=wall_ms,
        access_legs=extract_access_legs(bundle, enriched, solver),
    )


def solve_snapshot(
    enriched: "EnrichedSnapshot", budget_s: float = DEFAULT_BUDGET_SECONDS
) -> Solution:
    from .c01_c04 import build_model

    bundle = build_model(enriched)
    return solve(bundle, enriched, budget_s)
