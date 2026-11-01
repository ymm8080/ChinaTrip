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

import re
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


#: 演出场次串「多场（约15:00/20:00，旺季加场至4场）」「傍晚/晚间场（约
#: 17:30/19:30两场）」——场次列表是真值源（23552b5 show_sessions 刷新
#: 管线写入 opening_hours 列）。
_SESSION_LIST_RE = re.compile(r"约\s*((?:\d{1,2}:\d{2}\s*[/、,]\s*)+\d{1,2}:\d{2})")
_SESSION_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def show_session_starts(text: str | None) -> list[int]:
    """opening_hours 场次串 → 当日场次起点分钟表（升序去重）；解析不出回空。

    2026-10-31 上午空排事故根因之一：S5 把一切演出钉死 20:10-20:45
    晚场，白天多场演出（如《复活的军团》约11:10/12:00/13:40/16:20/
    17:10）同日多场被硬塞同一个 35 分钟晚窗 → 单日不可行 → 整单降级。
    场次表存在时 solver 应按真场次开窗（_visit_spec 场次点窗通道）。
    """
    if not text:
        return []
    starts: list[int] = []
    for m in _SESSION_LIST_RE.finditer(text):
        for hh, mm in _SESSION_TIME_RE.findall(m.group(1)):
            t = int(hh) * 60 + int(mm)
            if DAY_START_MINUTES <= t <= DAY_END_MINUTES:
                starts.append(t)
    return sorted(set(starts))


#: 2026-10-31 用户拍板（城墙·碑林 17:00 入场事故）：景区/博物馆等
#: 非演出类观光点只排白天，最晚 16:00 入场——傍晚档留给演出、
#: 夜游与晚餐。豁免：用户自钉时刻（铁律 19）、夜间属性点
#: （best_visit_time=evening/sunset）、营业时间明确开到晚间的场馆
#: （闭馆 ≥17:30）、餐饮/酒店/交通/演出类条目。
_GENERIC_ENTRY_CAP_MINUTES = 16 * 60
# 午餐软钉（2026-11-01 用户拍板修正：时刻最多提前或延后半小时、用餐
# 时长可缩短半小时）：初始排程的 12 点午餐锚是排程默认而非用户约束
# ——meal_flex=True（仅初次排程）时对 soft_pin 餐点开 ±30 分钟窗+
# 时长区间 [dur-30, dur]（保底 30 分钟）；用户手钉（soft_pin=False）
# 仍铁律 19 钉死。兜底层同口径的分层许可见 plan._fallback_sequence_times。
_MEAL_FLEX_SLIDE_MINUTES = 30
_MEAL_FLEX_SHORTEN_MINUTES = 30
_MEAL_FLEX_MIN_DURATION_MINUTES = 30
# 激活闸（2026-11-01）：当天存在 ≥150 分钟大点或 13:00 前场次的演出时
# 才动用软钉——普通日（60-120 分钟小点）零漂移（12:00 全时长），软钉
# 只在规则为之而设的场景（240 分钟华清池/12:30 场次挡午餐）生效。
_MEAL_FLEX_TRIGGER_DUR = 150
_LUNCH_PIN_FLEX_BEFORE_MIN = 15 * 60  # 15:00 前开餐的餐点才按午餐软钉
_LATE_OPEN_MINUTES = 17 * 60 + 30
_EVENING_OK_CATEGORIES = {"food", "entertainment", "hotel", "transport"}
_EVENING_OK_BEST = {"evening", "sunset", "show"}


def _hours_open_late(window: PoiHours | None) -> bool:
    """营业时间证明晚间可游（闭馆 ≥17:30；多段窗任一段满足即算）。"""
    if window is None:
        return False
    if window.windows:
        return any(
            _to_minutes(closes) >= _LATE_OPEN_MINUTES for _, closes in window.windows
        )
    if window.closes is None:
        return False
    return _to_minutes(window.closes) >= _LATE_OPEN_MINUTES


def generic_entry_cap(item: VisitItem, window: PoiHours | None) -> int | None:
    """非演出观光点的最晚入场分钟数；None = 不设闸（豁免面见常量注释）。"""
    if item.pinned:
        return None  # 铁律 19：用户确认过的时刻优先于默认排程规则
    if (item.best_visit_time or "") in _EVENING_OK_BEST:
        return None
    if (item.category or "") in _EVENING_OK_CATEGORIES:
        return None
    if _hours_open_late(window):
        return None
    return _GENERIC_ENTRY_CAP_MINUTES


_MINUTES_PER_DAY = 24 * 60


class _VisitSpec(NamedTuple):
    """Solved layout parameters for one VisitItem."""

    item: VisitItem
    lo: int  # earliest feasible start (minutes)
    hi: int  # latest feasible start (minutes)
    dur: int  # interval size upper bound (minutes)
    # G3 多段开窗（午休闭馆）：非 None 时 start 必须落其中一段
    # （solve_day 用条件约束 + ExactlyOne 建模，段外不可行）。
    windows: list[tuple[int, int]] | None = None
    # 2026-11-01 午餐软钉：时长可缩短时的下界（0=固定 dur——常规条目）。
    # 必须排在 windows 之后：位置构造 (item, lo, hi, dur, multi, dur_lo)。
    dur_lo: int = 0


def _to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _to_time(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def _visit_spec(
    item: VisitItem, hours: dict[str, PoiHours], *, meal_flex: bool = False
) -> _VisitSpec | None:
    """Compute the start domain for a visit; None = provably infeasible."""
    dur = item.duration_minutes
    if dur is None:
        dur = DEFAULT_VISIT_MINUTES
    if dur <= 0:
        return None

    lo, hi = DAY_START_MINUTES, DAY_END_MINUTES - dur
    dur_lo = 0  # 0=固定时长；软钉午餐在 pinned 分支激活区间下界
    # 8.2.1：时段属性先收窄开窗（lo=max(窗起, 08:00)、hi=min(窗止, 21:00)-
    # dur），再依次与营业时间窗、pinned 锚点收紧。未知枚举值按 "any" 处理
    # 不约束（防御库脏数据）；food 类条目不带该字段（plan.py 走 pinned 餐
    # 窗），天然不受影响。
    # 2026-10-31：带真场次的演出按场次点开窗（下方 multi 通道承载），
    # 不再吃 S5 晚场替换——白天多场演出不再被硬塞 20:10-20:45。
    # pinned 演出仍走原域（铁律 19：用户钉的时间优先于场次表）。
    show_sessions = (
        show_session_starts(item.opening_hours)
        if _is_show(item) and not item.pinned
        else []
    )
    if _is_show(item) and not show_sessions:
        # S5 场演窗：直接替换默认域（不看 _BEST_VISIT_WINDOWS——其 hi 会
        # 被 21:00 日终钳掉 20:10 开演）；营业时间窗仍照常再收紧。
        lo, hi = _SHOW_STARTS
    elif not _is_show(item):
        best = _BEST_VISIT_WINDOWS.get(item.best_visit_time or "")
        if best is not None:
            lo = max(lo, best[0])
            hi = min(hi, best[1] - dur)
    window = hours.get(item.poi_id) if item.poi_id is not None else None
    cap = generic_entry_cap(item, window)
    if cap is not None:
        # 白天入场闸（2026-10-31 拍板）：晚于闸点的入场时间不可行
        hi = min(hi, cap)
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

    if show_sessions:
        # 场次点窗：start 必恰落其中一个场次（段 (s, s)，G3 ExactlyOne 承载）
        multi = [(s, s) for s in show_sessions]

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
        if (
            meal_flex
            and item.soft_pin
            and (item.category or "") == "food"
            and pin < _LUNCH_PIN_FLEX_BEFORE_MIN
        ):
            # 午餐软钉 v2.2（2026-11-01 用户拍板：时刻最多提前或延后半小
            # 时、用餐时长可缩短半小时；仅初次排程 meal_flex=True 且仅系
            # 统钉 soft_pin）：±30 分钟开餐窗 + 时长区间 [dur-30, dur]
            # （保底 30 分钟）——上午大点与 12:30 场次点都能贴上午落位；
            # 晚餐（≥15:00 开餐）与用户手钉不受影响。
            lo = max(lo, pin - _MEAL_FLEX_SLIDE_MINUTES)
            hi = min(max(hi, pin), pin + _MEAL_FLEX_SLIDE_MINUTES)
            dur_lo = max(
                dur - _MEAL_FLEX_SHORTEN_MINUTES, _MEAL_FLEX_MIN_DURATION_MINUTES
            )
        else:
            lo = hi = pin
        multi = None

    if lo > hi:
        return None
    return _VisitSpec(item, lo, hi, dur, multi, dur_lo)


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
    sizes: list[object] | None = None,
    meal_penalty: object = 0,
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
            sz_i = sizes[i] if sizes is not None else specs[i].dur
            model.Add(starts[j] >= starts[i] + sz_i + gap).OnlyEnforceIf(lit)
    model.AddCircuit(arcs)
    # 软钉餐偏离惩罚（2026-11-01 规则：±30/缩 30 是许可不是偏好）：
    # travel×100 权重主导——省 ≥2 走行分钟才值得动午餐。
    model.Minimize(sum(costs) * 100 + meal_penalty)


def _add_makespan_objective(
    model: cp_model.CpModel,
    specs: list[_VisitSpec],
    starts: list[cp_model.IntVar],
    transfers: list[tuple[TransferItem, int, int]],
    *,
    sizes: list[object] | None = None,
    meal_penalty: object = 0,
) -> None:
    """Minimise the end of the last item of the day (earliest finish)."""
    # 弹性餐不计 makespan（2026-11-01）：餐不是日程的业务终点——缩餐/
    # 挪餐不再白嫖 makespan 收益；只有给参访腾结构空间时惩罚项才让位。
    # 纯餐日（无参访无交通）回退全员端点防空。
    _flexed = {i for i, sp in enumerate(specs) if sp.dur_lo and sp.dur_lo < sp.dur}
    _counted = [i for i in range(len(specs)) if i not in _flexed] or list(
        range(len(specs))
    )
    ends: list[cp_model.LinearExpr | int] = [
        starts[i] + (sizes[i] if sizes is not None else specs[i].dur) for i in _counted
    ]
    ends += [ts + tdur for _, ts, tdur in transfers]
    ub = max(
        [DAY_END_MINUTES]
        + [spec.hi + spec.dur for spec in specs]
        + [ts + tdur for _, ts, tdur in transfers]
    )
    makespan = model.NewIntVar(0, ub, "makespan")
    model.AddMaxEquality(makespan, ends)
    # 软钉餐偏离惩罚：makespan×100 权重主导（1 分钟 makespan > 最大偏离），
    # 无压力日零漂移+全时长。
    model.Minimize(makespan * 100 + meal_penalty)


def solve_day(
    day: DayPlan,
    *,
    poi_hours: list[PoiHours],
    travel_minutes: dict[tuple[str, str], int] | None = None,
    time_budget_seconds: float = 3.0,
    meal_flex: bool = False,
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
    # 激活闸：大点或早场次当天才 flex（普通日零漂移）
    flex_day = meal_flex and (
        any((v.duration_minutes or 0) >= _MEAL_FLEX_TRIGGER_DUR for v in visits)
        or any(
            _is_show(v)
            and any(s <= 13 * 60 for s in show_session_starts(v.opening_hours))
            for v in visits
        )
    )
    specs: list[_VisitSpec] = []
    for item in visits:
        spec = _visit_spec(item, hours, meal_flex=flex_day)
        if spec is None:
            return None
        specs.append(spec)

    def _attempt(separate: bool):
        """Build + solve the day model once; (solver, status, starts)."""
        model = cp_model.CpModel()
        starts: list[cp_model.IntVar] = []
        # 2026-11-01 午餐软钉：可缩时长的条目 size 是 IntVar（[dur_lo,dur]），
        # 其余沿用固定 int——输出端按类型取值。
        sizes: list[cp_model.IntVar | int] = []
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
            if spec.dur_lo and spec.dur_lo < spec.dur:
                size = model.NewIntVar(
                    spec.dur_lo, spec.dur, f"dur_{spec.item.item_id}"
                )
                sizes.append(size)
                # 本版 ortools 不收「双变量和」作 end——显式 end 变量+等式
                end = model.NewIntVar(
                    spec.lo + spec.dur_lo,
                    spec.hi + spec.dur,
                    f"end_{spec.item.item_id}",
                )
                model.Add(end == start + size)
                intervals.append(
                    model.NewIntervalVar(start, size, end, f"visit_{spec.item.item_id}")
                )
            else:
                sizes.append(spec.dur)
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
        for spec, start, size in zip(specs, starts, sizes):
            for _, ts, tdur in transfer_windows:
                before = model.NewBoolVar(f"before_{spec.item.item_id}_{ts}")
                model.Add(start + size <= ts - INTERCITY_BUFFER_MINUTES).OnlyEnforceIf(
                    before
                )
                model.Add(start >= ts + tdur + INTERCITY_BUFFER_MINUTES).OnlyEnforceIf(
                    before.Not()
                )

        # 软钉餐偏离惩罚项：|start-pin| + (dur - size)（激活软钉的餐才有）
        penalty_terms: list[object] = []
        for spec, start, size in zip(specs, starts, sizes):
            if not (spec.dur_lo and spec.dur_lo < spec.dur):
                continue
            pin = _to_minutes(spec.item.start_time) if spec.item.start_time else None
            if pin is None:
                continue
            drift = model.NewIntVar(
                0, _MEAL_FLEX_SLIDE_MINUTES, f"mdrift_{spec.item.item_id}"
            )
            model.AddAbsEquality(drift, start - pin)
            penalty_terms.append(drift + (spec.dur - size))
        meal_penalty = sum(penalty_terms) if penalty_terms else 0
        if travel_minutes is not None and specs:
            _add_travel_objective(
                model,
                specs,
                starts,
                travel_minutes,
                separate=separate,
                sizes=sizes,
                meal_penalty=meal_penalty,
            )
        else:
            _add_makespan_objective(
                model,
                specs,
                starts,
                transfer_windows,
                sizes=sizes,
                meal_penalty=meal_penalty,
            )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_budget_seconds
        solver.parameters.num_search_workers = 1  # deterministic schedules
        return solver, solver.Solve(model), starts, sizes

    solver, status, starts, sizes = _attempt(travel_minutes is not None and bool(specs))
    if (
        travel_minutes is not None
        and specs
        and status not in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    ):
        # 走行分离把当天挤爆（时段窗/转场缓冲卡死）→ 回落旧背靠背语义
        # 交付：宁可挤也不弃日（§6.9 降级链仍由上层兜底）。
        solver, status, starts, sizes = _attempt(False)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    placed: list[tuple[int, VisitItem | TransferItem]] = []
    for spec, start, size in zip(specs, starts, sizes):
        s = solver.Value(start)
        d = solver.Value(size) if not isinstance(size, int) else size
        update: dict[str, object] = {
            "start_time": _to_time(s),
            "end_time": _to_time(s + d),
        }
        if d != spec.dur:
            # 午餐软钉缩时长：条目时长同步为实值（卡片/后续重排一致）
            update["duration_minutes"] = d
        placed.append((s, spec.item.model_copy(update=update)))
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
    meal_flex: bool = False,
) -> ItineraryPlan | None:
    """Solve every day independently; a failing day keeps its input layout.

    2026-10-31 上午空排事故：旧「单日失败作废整单」让一个过约束日
    （晚场演出+返程航班缓冲）把其余各天的好解一起拖进顺序兜底，
    第 2/3 天上午全空。现在失败日原样保留（未排时间的条目由调用方
    的 _fallback_sequence_times 逐日收口），其余天保住 solver 优化解；
    调用方以「还有无 untimed 参访」判定是否降级披露。
    """
    solved_days: list[DayPlan] = []
    for day in plan.days:
        solved = solve_day(
            day,
            poi_hours=poi_hours,
            travel_minutes=travel_minutes,
            time_budget_seconds=time_budget_seconds,
            meal_flex=meal_flex,
        )
        solved_days.append(solved if solved is not None else day.model_copy(deep=True))
    return plan.model_copy(update={"days": solved_days})


#: §6.9 names the pipeline entrypoint ``solve_itinerary``; it is the
#: whole-plan solve.
solve_itinerary = solve_plan
