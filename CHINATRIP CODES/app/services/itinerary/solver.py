"""CP-SAT itinerary solver (design v2.0 §6.9).

Division of labour: the LLM owns understanding and POI selection; this
module owns feasibility and optimality of the schedule. Each visit is an
interval variable in the optional domain 08:00-21:00 with hard
constraints (opening-hour windows, no-overlap, intercity buffers around
fixed transfers, iron rule 19 pins) and a soft objective: minimise total
adjacent-pair travel when a matrix is supplied, else minimise makespan.

Degradation contract (§6.9): ``None`` = infeasible or no solution within
the time budget -> the caller falls back to the LLM self-repair chain
(<= 3 rounds). No partial day is ever returned.
"""

from __future__ import annotations

from datetime import time
from typing import NamedTuple

from ortools.sat.python import cp_model

from app.services.itinerary.models import (
    INTERCITY_BUFFER_MINUTES,
    DayPlan,
    ItineraryPlan,
    PoiHours,
    TransferItem,
    VisitItem,
)

#: Visits may be placed anywhere in [08:00, 21:00] (minutes since midnight).
DAY_START_MINUTES = 8 * 60
DAY_END_MINUTES = 21 * 60
#: Fallback when an item carries no duration.
DEFAULT_VISIT_MINUTES = 60
#: Fallback when the travel matrix has no entry for an ordered pair.
DEFAULT_TRAVEL_MINUTES = 30

_MINUTES_PER_DAY = 24 * 60


class _VisitSpec(NamedTuple):
    """Solved layout parameters for one VisitItem."""

    item: VisitItem
    lo: int  # earliest feasible start (minutes)
    hi: int  # latest feasible start (minutes)
    dur: int  # interval size (minutes)


def _to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _to_time(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def _visit_spec(item: VisitItem, hours: dict[str, PoiHours]) -> _VisitSpec | None:
    """Compute the start domain for a visit; None = provably infeasible."""
    dur = item.duration_minutes
    if dur is None:
        dur = DEFAULT_VISIT_MINUTES
    if dur <= 0:
        return None

    lo, hi = DAY_START_MINUTES, DAY_END_MINUTES - dur
    window = hours.get(item.poi_id) if item.poi_id is not None else None
    if window is not None:
        lo = max(lo, _to_minutes(window.opens))
        hi = min(hi, _to_minutes(window.closes) - dur)

    if item.pinned:  # iron rule 19: fixed at the user-confirmed time
        if item.start_time is None:
            return None
        pin = _to_minutes(item.start_time)
        if not lo <= pin <= hi:
            return None
        lo = hi = pin

    if lo > hi:
        return None
    return _VisitSpec(item, lo, hi, dur)


def _fixed_transfer_window(item: TransferItem) -> tuple[int, int] | None:
    """Resolve a transfer to a fixed (start, duration); None = unusable."""
    if item.start_time is None:
        return None
    ts = _to_minutes(item.start_time)
    if item.end_time is not None:
        te = _to_minutes(item.end_time)
        if te <= ts or te >= _MINUTES_PER_DAY:
            return None
        return ts, te - ts
    dur = item.duration_minutes
    if dur is None or dur <= 0 or ts + dur >= _MINUTES_PER_DAY:
        return None
    return ts, dur


def _travel_cost(a: VisitItem, b: VisitItem, matrix: dict[tuple[str, str], int]) -> int:
    """Matrix lookup by poi_id pair, then item_id pair, else default."""
    if a.poi_id is not None and b.poi_id is not None:
        cost = matrix.get((a.poi_id, b.poi_id))
        if cost is not None:
            return cost
    cost = matrix.get((a.item_id, b.item_id))
    if cost is not None:
        return cost
    return DEFAULT_TRAVEL_MINUTES


def _add_travel_objective(
    model: cp_model.CpModel,
    specs: list[_VisitSpec],
    starts: list[cp_model.IntVar],
    travel_minutes: dict[tuple[str, str], int],
) -> None:
    """Minimise total travel between chronologically adjacent visits.

    Ordering is modelled with an AddCircuit tour over a dummy depot: the
    tour (minus depot arcs) is the visit sequence; each non-depot arc
    forces its head to start after its tail ends, so the tour order and
    the chronological order coincide.
    """
    n = len(specs)
    arcs: list[tuple[int, int, cp_model.IntVar]] = []
    costs = []
    for j in range(n):  # depot -> first visit
        lit = model.NewBoolVar(f"first_{j}")
        arcs.append((0, j + 1, lit))
    for i in range(n):  # last visit -> depot
        lit = model.NewBoolVar(f"last_{i}")
        arcs.append((i + 1, 0, lit))
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            lit = model.NewBoolVar(f"arc_{i}_{j}")
            arcs.append((i + 1, j + 1, lit))
            costs.append(
                lit * _travel_cost(specs[i].item, specs[j].item, travel_minutes)
            )
            model.Add(starts[j] >= starts[i] + specs[i].dur).OnlyEnforceIf(lit)
    model.AddCircuit(arcs)
    model.Minimize(sum(costs))


def _add_makespan_objective(
    model: cp_model.CpModel,
    specs: list[_VisitSpec],
    starts: list[cp_model.IntVar],
    transfers: list[tuple[TransferItem, int, int]],
) -> None:
    """Minimise the end of the last item of the day (earliest finish)."""
    ends: list[cp_model.LinearExpr | int] = [
        starts[i] + specs[i].dur for i in range(len(specs))
    ]
    ends += [ts + tdur for _, ts, tdur in transfers]
    ub = max(
        [DAY_END_MINUTES]
        + [spec.hi + spec.dur for spec in specs]
        + [ts + tdur for _, ts, tdur in transfers]
    )
    makespan = model.NewIntVar(0, ub, "makespan")
    model.AddMaxEquality(makespan, ends)
    model.Minimize(makespan)


def solve_day(
    day: DayPlan,
    *,
    poi_hours: list[PoiHours],
    travel_minutes: dict[tuple[str, str], int] | None = None,
    time_budget_seconds: float = 3.0,
) -> DayPlan | None:
    """Order and time one day's items; None = infeasible or timed out.

    Every input item must appear in the output (no drops); if the full
    set cannot be scheduled the day fails atomically and None is
    returned so the caller can enter the §6.9 degradation chain.
    """
    visits = [i for i in day.items if isinstance(i, VisitItem)]
    transfers = [i for i in day.items if isinstance(i, TransferItem)]
    if not visits and not transfers:
        return day.model_copy(deep=True)

    transfer_windows: list[tuple[TransferItem, int, int]] = []
    for item in transfers:
        window = _fixed_transfer_window(item)
        if window is None:
            return None
        transfer_windows.append((item, window[0], window[1]))

    hours = {h.poi_id: h for h in poi_hours}
    specs: list[_VisitSpec] = []
    for item in visits:
        spec = _visit_spec(item, hours)
        if spec is None:
            return None
        specs.append(spec)

    model = cp_model.CpModel()
    starts: list[cp_model.IntVar] = []
    intervals: list[cp_model.IntervalVar] = []
    for spec in specs:
        start = model.NewIntVar(spec.lo, spec.hi, f"start_{spec.item.item_id}")
        starts.append(start)
        intervals.append(
            model.NewIntervalVar(
                start, spec.dur, start + spec.dur, f"visit_{spec.item.item_id}"
            )
        )
    for item, ts, tdur in transfer_windows:
        intervals.append(
            model.NewIntervalVar(ts, tdur, ts + tdur, f"transfer_{item.item_id}")
        )
    model.AddNoOverlap(intervals)

    # Visits keep INTERCITY_BUFFER_MINUTES clear on both sides of a transfer.
    for spec, start in zip(specs, starts):
        for _, ts, tdur in transfer_windows:
            before = model.NewBoolVar(f"before_{spec.item.item_id}_{ts}")
            model.Add(start + spec.dur <= ts - INTERCITY_BUFFER_MINUTES).OnlyEnforceIf(
                before
            )
            model.Add(start >= ts + tdur + INTERCITY_BUFFER_MINUTES).OnlyEnforceIf(
                before.Not()
            )

    if travel_minutes is not None and specs:
        _add_travel_objective(model, specs, starts, travel_minutes)
    else:
        _add_makespan_objective(model, specs, starts, transfer_windows)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_budget_seconds
    solver.parameters.num_search_workers = 1  # deterministic schedules
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    placed: list[tuple[int, VisitItem | TransferItem]] = []
    for spec, start in zip(specs, starts):
        s = solver.Value(start)
        placed.append(
            (
                s,
                spec.item.model_copy(
                    update={
                        "start_time": _to_time(s),
                        "end_time": _to_time(s + spec.dur),
                    }
                ),
            )
        )
    for item, ts, tdur in transfer_windows:
        updates: dict[str, time] = {}
        if item.end_time is None:
            updates["end_time"] = _to_time(ts + tdur)
        placed.append((ts, item.model_copy(update=updates)))
    placed.sort(key=lambda pair: (pair[0], pair[1].item_id))
    return DayPlan(day=day.day, base_city=day.base_city, items=[i for _, i in placed])


def solve_plan(
    plan: ItineraryPlan,
    *,
    poi_hours: list[PoiHours],
    travel_minutes: dict[tuple[str, str], int] | None = None,
    time_budget_seconds: float = 3.0,
) -> ItineraryPlan | None:
    """Solve every day; any single failure voids the whole plan."""
    solved_days: list[DayPlan] = []
    for day in plan.days:
        solved = solve_day(
            day,
            poi_hours=poi_hours,
            travel_minutes=travel_minutes,
            time_budget_seconds=time_budget_seconds,
        )
        if solved is None:
            return None
        solved_days.append(solved)
    return plan.model_copy(update={"days": solved_days})


#: §6.9 names the pipeline entrypoint ``solve_itinerary``; it is the
#: whole-plan solve.
solve_itinerary = solve_plan
