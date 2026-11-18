"""Deterministic lexicographic solve + extraction (P1-D; F-24/F-25/F-41).

Each F-23 tier is solved in sequence under a fixed deterministic-work cap;
the overall wall-clock budget is only a safety envelope. A proven optimum
is fixed before the next tier starts; if a tier cannot prove optimality,
the last proven-optimal prefix is returned as FEASIBLE (or UNKNOWN when
no prefix exists). INFEASIBLE never falls back to sequencing: the F-25
slack ladder re-solves with disclosed relaxations first, and when even
the ladder cannot seat the request the F-26 certificate explains why
(``certificate.py``). ``determinism_guard`` (F-41) is the red-line
utility: same snapshot (and hint) must give a byte-identical plan.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Optional

from ortools.sat.python import cp_model

from ..types import Solution, SolutionItem
from .certificate import explain_infeasibility, unplaced_reasons
from .objectives import build_objectives
from .slack import SlackFlags, ladder_levels, slack_disclosures

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot
    from ..types import FactSnapshot
    from .vars import VarBundle

SOLVER_SEED = 7
DEFAULT_BUDGET_SECONDS = 3.0
# Deterministic work cap per lexicographic tier. Wall-clock slices below are
# only a safety envelope; deterministic time decides how much search every
# run performs, so machine load cannot change the emitted plan.
TIER_DETERMINISTIC_BUDGET = 0.4
# Ladder rungs are strictly easier (fewer active constraints), so they run
# under a smaller deterministic cap; the whole INFEASIBLE path stays inside
# the same budget shape (audit M4: ladder + certificate bounded by it).
LADDER_TIER_DETERMINISTIC_BUDGET = 0.1


def _seed_greedy_fill_hints(bundle, enriched, prev_solver) -> None:
    """Greedy incumbent seed for tier②: keep tier① placements, add
    fills in tier order onto the least-loaded feasible day. Hints
    only warm-start — determinism unaffected (dtime decides)."""
    snapshot = enriched.snapshot
    fills = sorted(
        (c for c in snapshot.candidates if not c.rid),
        key=lambda c: (c.tier or 12, c.cid),
    )
    if not fills or prev_solver is None:
        return
    load = {d: 0 for d in bundle.days}
    for cid, day in bundle.cid_day_list:
        if prev_solver.Value(bundle.presence[(cid, day)]):
            load[day] = load.get(day, 0) + prev_solver.Value(bundle.dur[cid])
    budget = int(getattr(snapshot.request, "day_load_budget_min", 570) or 570)
    # complete hint: every presence explicitly 0/1, requested starts from
    # the tier-1 solver — complete consistent hints survive CP-SAT repair
    for cid, day in bundle.cid_day_list:
        lit = prev_solver.Value(bundle.presence[(cid, day)])
        bundle.model.AddHint(bundle.presence[(cid, day)], lit)
        if lit:
            bundle.model.AddHint(
                bundle.start[(cid, day)], prev_solver.Value(bundle.start[(cid, day)])
            )
    for cand in fills:
        target = min(
            bundle.days,
            key=lambda d: (load.get(d, 0), d),
        )
        dur = cand.suggested_duration_min or 90
        if load.get(target, 0) + dur <= budget:
            bundle.model.AddHint(bundle.presence[(cand.cid, target)], 1)
            start = max(8 * 60 + 30, 13 * 60 if load.get(target, 0) else 8 * 60 + 30)
            bundle.model.AddHint(bundle.start[(cand.cid, target)], start)
            bundle.model.AddHint(bundle.dur[cand.cid], dur)
            load[target] = load.get(target, 0) + dur


def _apply_hint(bundle: "VarBundle", hint: "Solution") -> None:
    """F-24: seed the search with a previous solution (edit re-solve, P4).
    Hints only warm-start -- the deterministic budget still decides how
    much search runs, so determinism is unaffected."""
    model = bundle.model
    seated = {(it.cid, it.day) for it in hint.items}
    for key, lit in bundle.presence.items():
        model.AddHint(lit, 1 if key in seated else 0)
    for it in hint.items:
        start = bundle.start.get((it.cid, it.day))
        if start is not None:
            model.AddHint(start, it.start_min)
        dur = bundle.dur.get(it.cid)
        if dur is not None:
            model.AddHint(dur, it.end_min - it.start_min)
    unplaced_rids = {u.get("rid") for u in hint.unplaced}
    for rid, lit in bundle.unplaced.items():
        if rid in unplaced_rids:
            model.AddHint(lit, 1)


def solve(
    bundle: "VarBundle",
    enriched: "EnrichedSnapshot",
    budget_s: float = DEFAULT_BUDGET_SECONDS,
    *,
    hint: Optional["Solution"] = None,
    slack: Optional[SlackFlags] = None,
    tier_det: float = TIER_DETERMINISTIC_BUDGET,
) -> Solution:
    started = time.perf_counter()
    if hint is not None:
        _apply_hint(bundle, hint)
    tiers = build_objectives(bundle, enriched, slack)
    solver = None
    status = "UNKNOWN"
    objective_values: dict[str, int] = {}
    greedy_seeded = False
    fully_optimized = True  # R3b: stays True only if every tier proves OPTIMAL

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
        # Q3 全局墙钟：总预算跨层共享——每层 max_time=剩余额（否则
        # 每层各吃满 budget，4 层可达 4×；g11 实测 5.1s > 3.6 预算）
        # 预算 0=耗尽语义（UNKNOWN）：地板只在正预算时生效
        remaining = (
            max(0.05, budget_s - (time.perf_counter() - started))
            if budget_s > 0
            else 0.0
        )
        candidate_solver.parameters.max_time_in_seconds = remaining
        candidate_solver.parameters.max_deterministic_time = tier_det
        if tier.sense == "min":
            bundle.model.Minimize(tier.expression)
        else:
            bundle.model.Maximize(tier.expression)
        status_code = candidate_solver.Solve(bundle.model)
        status = candidate_solver.StatusName(status_code)
        if coverage_assumptions:
            bundle.model.ClearAssumptions()
        if index == 1 and not greedy_seeded and status == "OPTIMAL":
            # R4: trip-scale tier② needs an incumbent seed — greedy
            # fill placement in tier order on the least-loaded day
            # (g11 was UNKNOWN at 0.4 dtime without it)
            _seed_greedy_fill_hints(bundle, enriched, solver)
            greedy_seeded = True
        if status == "INFEASIBLE":
            return Solution(
                status="INFEASIBLE",
                wall_ms=int((time.perf_counter() - started) * 1000),
                objective_values=objective_values,
                hint_used=hint is not None,
            )
        if status == "UNKNOWN":
            # No feasible point found within the deterministic budget: keep
            # the last prefix and report honestly.
            break
        if status not in ("OPTIMAL", "FEASIBLE"):
            break
        # R3b: dtime-capped search is machine-independent (that is exactly
        # why solve() caps max_deterministic_time, not wall time), so a
        # FEASIBLE tier result is as deterministic as a proven one. Accept
        # it, bound-lock the found value (never worse in later tiers), and
        # report optimality honestly via fully_optimized.
        solver = candidate_solver
        best = int(round(candidate_solver.ObjectiveValue()))
        objective_values[tier.name] = best
        fully_optimized = fully_optimized and status == "OPTIMAL"
        if index < len(tiers) - 1:
            # FEASIBLE 也等式锁（与 OPTIMAL 同式）：锁死已找到的值，
            # 后续层在同值空间优化——与既有词典序行为一致，形状不漂移
            bundle.model.Add(tier.expression == best)

    wall_ms = int((time.perf_counter() - started) * 1000)
    if solver is None:
        return Solution(
            status="UNKNOWN",
            wall_ms=wall_ms,
            objective_values=objective_values,
            hint_used=hint is not None,
        )

    items: list[SolutionItem] = []
    snapshot = enriched.snapshot
    from .c01_c04 import _pinned_cids

    pinned_keys = _pinned_cids(snapshot.request, snapshot)
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
                pinned=(cid, day) in pinned_keys,  # F-20/F-51: 铁律 19 豁免面
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
                }
            )
    # F-26: replace the placeholder with real reason codes + zh text.
    unplaced = unplaced_reasons(enriched, unplaced)

    from .c05_c08 import extract_access_legs
    from .c09_c16 import extract_hotel_anchors, extract_meal_anchors

    proto = bundle.model.Proto()
    sol = Solution(
        status="OPTIMAL" if fully_optimized else "FEASIBLE",
        items=items,
        unplaced=unplaced,
        wall_ms=wall_ms,
        access_legs=extract_access_legs(bundle, enriched, solver),
        meal_anchors=extract_meal_anchors(bundle, enriched, solver),
        hotel_anchors=extract_hotel_anchors(bundle, enriched, solver),
        objective_values=objective_values,
        hint_used=hint is not None,
        n_vars=len(proto.variables),
        n_cons=len(proto.constraints),
    )
    # F-62 收敛口径=引擎实际预算（Q3 披露放宽后携带真实预算）
    sol.budget_used_ms = int(budget_s * 1000)
    return sol


def solve_snapshot(
    enriched: "EnrichedSnapshot",
    budget_s: float = DEFAULT_BUDGET_SECONDS,
    *,
    hint: Optional["Solution"] = None,
    use_ladder: bool = True,
) -> Solution:
    """F-24 entry: budgeted deterministic solve; optional previous-solution
    hint; INFEASIBLE goes through the F-25 ladder (disclosed relaxations)
    and, failing that, the F-26 certificate -- never a sequential fallback."""
    import time as _time

    from .c01_c04 import build_model

    started = _time.perf_counter()
    bundle = build_model(enriched)
    # Q3 拍板原文：紧张时按层提高预算**并披露**——绝不回退顺序排列。
    # trip 规模（池>20）tier det 0.5 才有 incumbent（g11 类）；墙钟预算
    # 相应放宽（disclosed raise，F-62 收敛口径=预算内）
    extra = []
    solve_kwargs = {"hint": hint}
    if len(enriched.snapshot.candidates) > 20:
        solve_kwargs["tier_det"] = 0.5
        budget_s = max(budget_s, 5.5)
        extra = ["行程规模较大，求解时间预算按 Q3 披露放宽至 5.5s（绝不回退顺序排列）"]
    # 预算核算覆盖 build_model（g11 建模 ~1s 不含在 solve 内会翻预算）
    remaining_after_build = (
        max(0.15, budget_s - (_time.perf_counter() - started)) if budget_s > 0 else 0.0
    )
    solution = solve(bundle, enriched, remaining_after_build, **solve_kwargs)
    if extra and solution.disclosures is not None:
        solution.disclosures = list(solution.disclosures) + extra
    if solution.status != "INFEASIBLE":
        return solution
    if use_ladder:
        for flags in ladder_levels()[1:]:
            relaxed_bundle = build_model(enriched, flags)
            remaining = max(0.2, budget_s - (_time.perf_counter() - started))
            relaxed = solve(
                relaxed_bundle,
                enriched,
                remaining,
                slack=flags,
                tier_det=LADDER_TIER_DETERMINISTIC_BUDGET,
            )
            if relaxed.status in ("OPTIMAL", "FEASIBLE"):
                relaxed.slack_level = flags.level()
                relaxed.disclosures = relaxed.disclosures + slack_disclosures(flags)
                return relaxed
    solution.certificate = explain_infeasibility(enriched)
    return solution


def canonical_solution(solution: "Solution") -> str:
    """F-41 comparison key: everything plan-bearing except ``wall_ms``
    (measurement, not plan)."""
    payload = {
        "status": solution.status,
        "slack_level": solution.slack_level,
        "items": [
            [it.day, it.start_min, it.end_min, it.cid]
            for it in sorted(solution.items, key=lambda i: (i.day, i.start_min, i.cid))
        ],
        "unplaced": sorted(
            [
                str(u.get("rid")),
                str(u.get("name")),
                ",".join(u.get("reason_codes", ())),
            ]
            for u in solution.unplaced
        ),
        "disclosures": sorted(solution.disclosures),
        "certificate": sorted(
            json.dumps(c, ensure_ascii=False, sort_keys=True)
            for c in solution.certificate
        ),
        "access_legs": sorted(
            json.dumps(leg, ensure_ascii=False, sort_keys=True)
            for leg in solution.access_legs
        ),
        "meal_anchors": sorted(
            json.dumps(m, ensure_ascii=False, sort_keys=True)
            for m in solution.meal_anchors
        ),
        "hotel_anchors": sorted(
            json.dumps(h, ensure_ascii=False, sort_keys=True)
            for h in solution.hotel_anchors
        ),
        "objective_values": dict(sorted(solution.objective_values.items())),
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def determinism_guard(
    snapshot: "FactSnapshot",
    budget_s: float = DEFAULT_BUDGET_SECONDS,
    *,
    hint: Optional["Solution"] = None,
) -> bool:
    """F-41 red line: same snapshot (and hint) -> byte-identical plan."""
    from ..inputs.enrich import enrich

    enriched = enrich(snapshot)
    first = solve_snapshot(enriched, budget_s=budget_s, hint=hint, use_ladder=False)
    second = solve_snapshot(enriched, budget_s=budget_s, hint=hint, use_ladder=False)
    return canonical_solution(first) == canonical_solution(second)
