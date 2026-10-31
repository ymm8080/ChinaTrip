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

#: Visits may be placed anywhere in [09:00, 21:00] (minutes since midnight).
# 2026-10-31 拍板：景点活动一天 9 点开始（8 点太早）；交通除外——
# 车次/航班时刻是客观固定窗，不受此日始钳制（火车 8 点出发照常）。
DAY_START_MINUTES = 9 * 60
DAY_END_MINUTES = 21 * 60
#: Fallback when an item carries no duration.
DEFAULT_VISIT_MINUTES = 60
#: Fallback when the travel matrix has no entry for an ordered pair.
DEFAULT_TRAVEL_MINUTES = 30
# 0009 / 8.2.1：best_visit_time 枚举 → 时段窗（分钟，[起, 止)）。表内不收
# "any"：字段为 None/"any"/未知脏值时查表落空，按全天窗处理不约束。
_BEST_VISIT_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (9 * 60, 12 * 60),  # 09:00-12:00（随日始 9 点，2026-10-31）
    "afternoon": (12 * 60, 17 * 60),  # 12:00-17:00
    "evening": (17 * 60, 21 * 60),  # 17:00-21:00（夜景自动排晚上）
    "sunset": (16 * 60, 19 * 60),  # 16:00-19:00 近似窗
    "sunrise": (9 * 60, 10 * 60 + 30),  # 09:00-10:30 近似窗（随日始）
}

#: S5（show_booking_design §4，2026-10-26）：演出=晚间场演事件——
#: 开演域 20:10-20:45（散场至 21:30 前后），允许越常规日终 21:00
#: （场演即当日收尾事件，后续无排项）。触发：库行 best_visit_time="show"
#: （import_shows 种子）或 category=entertainment。
_SHOW_STARTS = (20 * 60 + 10, 20 * 60 + 45)


def _is_show(item: VisitItem) -> bool:
    return item.best_visit_time == "show" or item.category == "entertainment"


_MINUTES_PER_DAY = 24 * 60


class _VisitSpec(NamedTuple):
    """Solved layout parameters for one VisitItem."""

    item: VisitItem
    lo: int  # earliest feasible start (minutes)
    hi: int  # latest feasible start (minutes)
    dur: int  # interval size (minutes)
    # G3 多段开窗（午休闭馆）：非 None 时 start 必须落其中一段
    # （solve_day 用条件约束 + ExactlyOne 建模，段外不可行）。
    windows: list[tuple[int, int]] | None = None


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
    # 8.2.1：时段属性先收窄开窗（lo=max(窗起, 08:00)、hi=min(窗止, 21:00)-
    # dur），再依次与营业时间窗、pinned 锚点收紧。未知枚举值按 "any" 处理
    # 不约束（防御库脏数据）；food 类条目不带该字段（plan.py 走 pinned 餐
    # 窗），天然不受影响。
    if _is_show(item):
        # S5 场演窗：直接替换默认域（不看 _BEST_VISIT_WINDOWS——其 hi 会
        # 被 21:00 日终钳掉 20:10 开演）；营业时间窗仍照常再收紧。
        lo, hi = _SHOW_STARTS
    else:
        best = _BEST_VISIT_WINDOWS.get(item.best_visit_time or "")
        if best is not None:
            lo = max(lo, best[0])
            hi = min(hi, best[1] - dur)
    window = hours.get(item.poi_id) if item.poi_id is not None else None
    multi: list[tuple[int, int]] | None = None
    if window is not None and window.windows:
        # G3：多段（如 09:00-12:00 + 13:30-17:00）——逐段与全天/best 窗
        # 相交，段内可行起点域 [seg_lo, seg_hi-dur]；存活段 >1 才多段建模。
        multi = []
        for opens, closes in window.windows:
            seg_lo = max(_to_minutes(opens), lo)
            seg_hi = min(_to_minutes(closes), hi + dur)
            if seg_lo <= seg_hi - dur:
                multi.append((seg_lo, seg_hi - dur))
        if not multi:
            return None
        lo, hi = min(s[0] for s in multi), max(s[1] for s in multi)
        if len(multi) == 1:
            lo, hi = multi[0]
            multi = None
    elif window is not None:
        lo = max(lo, _to_minutes(window.opens))
        hi = min(hi, _to_minutes(window.closes) - dur)

    if item.pinned:  # iron rule 19: fixed at the user-confirmed time
        if item.start_time is None:
            return None
        pin = _to_minutes(item.start_time)
        # 日始 9 点（2026-10-31）是排程默认而非用户约束：用户自钉的
        # 早于日始的时刻照常生效（铁律 19 优先，validate_plan 另行提示）
        if pin < lo:
            lo = pin
        if multi is not None:
            if not any(s[0] <= pin <= s[1] for s in multi):
                return None
        elif not lo <= pin <= hi:
            return None
        lo = hi = pin
        multi = None

    if lo > hi:
        return None
    return _VisitSpec(item, lo, hi, dur, multi)


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
    *,
    separate: bool = False,
) -> None:
    """Minimise total travel between chronologically adjacent visits.

    Ordering is modelled with an AddCircuit tour over a dummy depot: the
    tour (minus depot arcs) is the visit sequence; each non-depot arc
    forces its head to start after its tail ends, so the tour order and
    the chronological order coincide.

    separate=True（2026-10-30）：弧约束再叠加相邻两点的走行分钟——旧版
    只把 travel 计进目标函数、不进时序约束，日程排得出「上一场 09:30
    散场、7.3km 外下一场 09:30 开场」的零走行衔接。分离态不可行时
    solve_day 回落旧语义（宁可背靠背也不弃日）。
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
            gap = (
                _travel_cost(specs[i].item, specs[j].item, travel_minutes)
                if separate
                else 0
            )
            model.Add(starts[j] >= starts[i] + specs[i].dur + gap).OnlyEnforceIf(lit)
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

    def _attempt(separate: bool):
        """Build + solve the day model once; (solver, status, starts)."""
        model = cp_model.CpModel()
        starts: list[cp_model.IntVar] = []
        intervals: list[cp_model.IntervalVar] = []
        for spec in specs:
            start = model.NewIntVar(spec.lo, spec.hi, f"start_{spec.item.item_id}")
            starts.append(start)
            if spec.windows:
                # G3 多段开窗：start 必落其中一段（条件约束 + ExactlyOne，
                # 标准解法——不引入 optional intervals，模型更简）
                presences = []
                for j, (wlo, whi) in enumerate(spec.windows):
                    in_win = model.NewBoolVar(f"inwin_{spec.item.item_id}_{j}")
                    model.Add(start >= wlo).OnlyEnforceIf(in_win)
                    model.Add(start <= whi).OnlyEnforceIf(in_win)
                    presences.append(in_win)
                model.AddExactlyOne(presences)
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

        # Visits keep INTERCITY_BUFFER_MINUTES clear on both sides of a
        # transfer.
        for spec, start in zip(specs, starts):
            for _, ts, tdur in transfer_windows:
                before = model.NewBoolVar(f"before_{spec.item.item_id}_{ts}")
                model.Add(
                    start + spec.dur <= ts - INTERCITY_BUFFER_MINUTES
                ).OnlyEnforceIf(before)
                model.Add(start >= ts + tdur + INTERCITY_BUFFER_MINUTES).OnlyEnforceIf(
                    before.Not()
                )

        if travel_minutes is not None and specs:
            _add_travel_objective(
                model, specs, starts, travel_minutes, separate=separate
            )
        else:
            _add_makespan_objective(model, specs, starts, transfer_windows)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_budget_seconds
        solver.parameters.num_search_workers = 1  # deterministic schedules
        return solver, solver.Solve(model), starts

    solver, status, starts = _attempt(travel_minutes is not None and bool(specs))
    if (
        travel_minutes is not None
        and specs
        and status not in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    ):
        # 走行分离把当天挤爆（时段窗/转场缓冲卡死）→ 回落旧背靠背语义
        # 交付：宁可挤也不弃日（§6.9 降级链仍由上层兜底）。
        solver, status, starts = _attempt(False)
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
