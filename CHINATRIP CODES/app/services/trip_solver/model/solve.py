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


#: R41 餐绑定打磨的确定性预算：非餐分日钉死后搜索面只剩「餐槽绑谁 + 时刻
#: 微调」，incumbent 完整热启动下第一组可行解几乎立刻可得。
MEAL_POLISH_DETERMINISTIC_BUDGET = 0.35


def _polish_meal_bindings(bundle, enriched, pref_tier, base_solver, floor, *, wall_s):
    """R41：分日锁死后的**餐绑定打磨**（小求解，与 preference 大层解耦）。

    动机（2026-11-25 用户「附近餐厅都没有被推荐插入到餐卡」真库实测）：
    命名餐的全部收益都在 preference 大层，默认预算（0.75-0.95 dtime）下该层
    经常只还回带缺口的 FEASIBLE，甚至整层 UNKNOWN——两种形态端上都是
    「附近餐厅一张都没进餐卡」。把非餐候选的**分日**钉到当前 incumbent 后，
    同一套约束里可动的只剩餐槽绑定与时刻微调，搜索面小几个量级；再以
    incumbent 做完整热启动，第一组合法解即刻可得，随后就地把命名餐补齐。

    词典序不被破坏：
    - coverage/weather/day_hint 等已锁层的等式约束仍在模型里；
    - 非餐分日被钉 → 必去覆盖与已锁层目标天然不变；
    - preference 目标以 incumbent 值为地板（floor 非空时），只接受不更差的解；
      调用方随后用打磨值做等式锁，后续层看到的仍是同一词典序契约。
    - 任何失败/超时返回 None，调用方保留原 incumbent（行为与旧版一致）。
    """
    snapshot = enriched.snapshot
    meal_cids = {
        c.cid
        for c in snapshot.candidates
        if (c.category or "") == "food" and getattr(c, "meal_slot", None)
    }
    if not meal_cids or base_solver is None or wall_s <= 0.02:
        return None
    model = bundle.model
    maximize = getattr(pref_tier, "sense", "max") != "min"
    # 钉分日只用 **assumptions**（与 coverage 层同款机制），不往模型里加
    # 任何约束：收工 ClearAssumptions + ClearHints 即还原，后续 travel/
    # makespan 层看到的仍是原模型（upb 的 repeated constraints 不支持删除，
    # 约束式钉法会污染后续层）。目标地板改为求解后比对，同样无需加约束。
    for cid, day in bundle.cid_day_list:
        if cid in meal_cids:
            continue
        lit = bundle.presence[(cid, day)]
        model.AddAssumptions([lit if base_solver.Value(lit) else lit.Not()])
    # 完整热启动 = incumbent 本身：钉非分日假设下它仍然可行，因此打磨几乎
    # 不可能 UNKNOWN（旧层「搜不到任何可行点」的失灵形态到此为止）。
    model.ClearHints()  # 同一变量重复 AddHint 会 MODEL_INVALID（R8-S4 教训）
    for cid, day in bundle.cid_day_list:
        model.AddHint(
            bundle.presence[(cid, day)],
            base_solver.Value(bundle.presence[(cid, day)]),
        )
        model.AddHint(
            bundle.start[(cid, day)], base_solver.Value(bundle.start[(cid, day)])
        )
    for cid, var in bundle.dur.items():
        model.AddHint(var, base_solver.Value(var))
    for key, lit in bundle.meal_bound.items():
        model.AddHint(lit, base_solver.Value(lit))
    if maximize:
        model.Maximize(pref_tier.expression)
    else:
        model.Minimize(pref_tier.expression)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = SOLVER_SEED
    solver.parameters.max_time_in_seconds = wall_s
    solver.parameters.max_deterministic_time = MEAL_POLISH_DETERMINISTIC_BUDGET
    status = solver.Solve(model)
    model.ClearAssumptions()
    model.ClearHints()
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    if floor is not None:
        value = solver.ObjectiveValue()
        if (maximize and value < floor) or (not maximize and value > floor):
            return None  # 不如 incumbent：不采纳（调用方保留原解）
    return solver, solver.StatusName(status)


def _seed_greedy_fill_hints(bundle, enriched, prev_solver) -> None:
    """Greedy incumbent seed for tier②: keep tier① placements, add
    fills in tier order onto the least-loaded feasible day. Hints
    only warm-start — determinism unaffected (dtime decides).

    R8-S4：提示单字典合并——同一变量只提一次（旧版先按 tier① 解全量
    提示、贪心又对 presence/dur 重复提不同值 → CP-SAT MODEL_INVALID，
    阶梯静默断在后续层；all-fill 空排根因之四）。同日光标推进避让
    tier① 已排项（end+45min），溢出日尾从头再排（CP-SAT 小修）。"""
    snapshot = enriched.snapshot
    fills = sorted(
        (c for c in snapshot.candidates if not c.rid),
        key=lambda c: (c.tier or 12, c.cid),
    )
    if not fills or prev_solver is None:
        return
    load = {d: 0 for d in bundle.days}
    cursor = {d: 0 for d in bundle.days}
    for cid, day in bundle.cid_day_list:
        if prev_solver.Value(bundle.presence[(cid, day)]):
            end = prev_solver.Value(bundle.start[(cid, day)]) + prev_solver.Value(
                bundle.dur[cid]
            )
            load[day] = load.get(day, 0) + prev_solver.Value(bundle.dur[cid])
            cursor[day] = max(cursor.get(day, 0), end)
    budget = int(getattr(snapshot.request, "day_load_budget_min", 570) or 570)
    # complete hint: every presence explicitly 0/1, requested starts from
    # the tier-1 solver — collected in ONE dict, applied once (no dup).
    hint_vals: dict = {}
    for cid, day in bundle.cid_day_list:
        lit = prev_solver.Value(bundle.presence[(cid, day)])
        hint_vals[bundle.presence[(cid, day)]] = lit
        if lit:
            hint_vals[bundle.start[(cid, day)]] = prev_solver.Value(
                bundle.start[(cid, day)]
            )
    for cand in fills:
        target = min(
            bundle.days,
            key=lambda d: (load.get(d, 0), d),
        )
        dur = cand.suggested_duration_min or 90
        if load.get(target, 0) + dur <= budget:
            day_open, day_close = 8 * 60 + 30, 21 * 60
            start = max(day_open, cursor.get(target, 0))
            if start + dur > day_close:
                start = day_open
            hint_vals[bundle.presence[(cand.cid, target)]] = 1
            hint_vals[bundle.start[(cand.cid, target)]] = start
            hint_vals[bundle.dur[cand.cid]] = dur
            cursor[target] = start + dur + 45
            load[target] = load.get(target, 0) + dur
    for var, val in hint_vals.items():
        bundle.model.AddHint(var, val)


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
    tier2_det: Optional[float] = None,
) -> Solution:
    started = time.perf_counter()
    # R31: C-06 may have yielded to the user's written day plan at build time.
    c06_yielded = bool(getattr(bundle, "c06_yielded_to_day_plan", False))
    if hint is not None:
        _apply_hint(bundle, hint)
    tiers = build_objectives(bundle, enriched, slack)
    # R25c：写明的天作为搜索种子（hint 只暖启动，不改确定性口径）——
    # 使 day_hint/coverage 层第一个 incumbent 就是「按写的天」，截断 FEASIBLE 不会
    # 锁死一个被换乱的初解（R25c live 实测：天块整体漂移的根因）。
    _blocks = getattr(bundle, "c25_day_blocks", None) or {}
    for (_hd, _d), _var in (_blocks.get("vars") or {}).items():
        bundle.model.AddHint(_var, 1 if int(_d) == int(_hd) else 0)
    solver = None
    status = "UNKNOWN"
    objective_values: dict[str, int] = {}
    greedy_seeded = False
    fully_optimized = True  # R3b: stays True only if every tier proves OPTIMAL

    # R12-H19（2026-11-20 用户拍板「当第二天删去天安门、颐和园后 时间
    # 有富裕可以回插一个 MUST VISIT 小景点。所以天安门能安排的下」）：
    # 必去回插预检——覆盖层 dtime 帽内会把「多弃」次优解等式锁冻死
    # （BJ 实锤：双弃 234 锁住，单弃 231 家族没被搜到、天安门被冤弃）。
    # 最小弃排梯：k=0 全排 → k=1 按覆盖权重序单弃 → 首个可行即硬锁弃排
    # 集；全探不可行才放开自然删点序（覆盖层自决，诚实披露）。
    _req = getattr(enriched.snapshot.request, "musts", ()) or ()
    _unp = {r.rid: bundle.unplaced[r.rid] for r in _req if r.rid in bundle.unplaced}
    # R12-H19b：语料级大模型跳梯——6 探针 × 0.3 dtime 会吃爆 3s 总预
    # 算（g11 实锤 UNKNOWN 5.7s）；小模型（BJ 实测 50 对）梯照常。
    _ladder_ok = len(enriched.snapshot.candidates) * len(bundle.days) <= 150
    if _unp and _ladder_ok:

        def _probe() -> cp_model.CpSolver:
            s = cp_model.CpSolver()
            s.parameters.num_workers = 1
            s.parameters.random_seed = SOLVER_SEED
            s.parameters.max_deterministic_time = 0.1
            return s

        _weights = {r.rid: max(1, r.importance) for r in _req}
        for c in enriched.snapshot.candidates:
            if c.rid and c.kind == "requested" and getattr(c, "quality", None):
                try:
                    _weights[c.rid] = _weights.get(c.rid, 1) * max(
                        1, int(float(c.quality))
                    )
                except Exception:
                    pass
        _remote_rids = {
            c.rid
            for c in enriched.snapshot.candidates
            if c.rid and (c.poi_id or c.cid) in enriched.access_by_poi
        }
        if _remote_rids:
            _city_ws = [w for rid, w in _weights.items() if rid not in _remote_rids]
            if _city_ws:
                _top = max(_city_ws)
                for rid in _remote_rids:
                    if rid in _weights:
                        _weights[rid] = max(_weights[rid], _top + 1)
        _locked = None
        bundle.model.AddAssumptions([v.Not() for v in _unp.values()])
        _st = _probe().Solve(bundle.model)
        bundle.model.ClearAssumptions()
        if _st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            _locked = {}
        elif _st == cp_model.INFEASIBLE:
            # R34: only a *proven* INFEASIBLE k=0 justifies the single-drop
            # sweep. UNKNOWN means the 0.1 deterministic-time probe could
            # neither seat all musts nor prove they cannot all be seated —
            # so the one-drop probes (same model, same dtime) cannot decide
            # anything either. Real profile: a 33-candidate / 12-must / 4-day
            # trip burned 13 x ~330ms = 4.28s (72% of the whole solve) on
            # probes that ALL returned UNKNOWN, locking nothing. Bail out
            # and let the coverage tier (larger dtime) decide placement.
            for _rid in sorted(_unp, key=lambda x: _weights.get(x, 1)):
                _others = [v.Not() for x, v in _unp.items() if x != _rid]
                bundle.model.AddAssumptions(_others)
                _st = _probe().Solve(bundle.model)
                bundle.model.ClearAssumptions()
                if _st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    _locked = {_rid}
                    break
        if _locked is not None:
            for _rid, _v in _unp.items():
                bundle.model.Add(_v == (1 if _rid in _locked else 0))

    # R13g：墙帽污染账——任一层的墙钟帽先于 det-time 触发即记真
    # （求解被墙钟截断=结果负载敏感；对照见 Solution.wall_capped）。
    wall_capped = False
    # R41：有餐候选时，preference 层后接一次「钉分日」的餐绑定打磨（见
    # _polish_meal_bindings），并给它预留墙钟——打磨只吃 0.35 det，通常
    # 零点几秒内返回。
    has_meals = any(
        (c.category or "") == "food" and getattr(c, "meal_slot", None)
        for c in enriched.snapshot.candidates
    )
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
        _wall = remaining
        if tier.name == "preference" and has_meals:
            _wall = max(0.05, remaining - min(1.0, remaining * 0.3))
        candidate_solver.parameters.max_time_in_seconds = _wall
        # R8-S4：tier②（fill 最大化）专属 dtime——大池 all-fill 的
        # 病灶层（36×5 在 0.4/0.5 下 UNKNOWN=空排）；其余层维持
        # R5 调好的口径（g11 墙钟不被拖爆）。
        # R25c：层序名化——插入 weather_days/day_hint 后 index 不再等价于名字。
        _det = (
            tier2_det
            if (tier.name == "preference" and tier2_det is not None)
            else tier_det
        )
        if tier.name in ("day_hint", "weather_days"):
            _det = max(_det, 1.2)
        candidate_solver.parameters.max_deterministic_time = _det
        if tier.sense == "min":
            bundle.model.Minimize(tier.expression)
        else:
            bundle.model.Maximize(tier.expression)
        status_code = candidate_solver.Solve(bundle.model)
        status = candidate_solver.StatusName(status_code)
        # 判据宽松偏向标真（多标只多付对照对，绝不漏标=绝不把负载
        # 抖动当引擎确定性回归）：WallTime 贴到帽（±0.1s）即视为墙截断
        if candidate_solver.WallTime() >= remaining - 0.1:
            wall_capped = True
        if coverage_assumptions:
            bundle.model.ClearAssumptions()
        if tier.name == "preference" and has_meals:
            # R41：钉分日打磨餐绑定。层 UNKNOWN 时以「上一层 incumbent」为底
            # （此时该层还没加等式锁，打磨可自由优化 preference）；层成功时
            # 以本层值为地板，只接受不更差的解。
            _base = candidate_solver if status in ("OPTIMAL", "FEASIBLE") else solver
            _floor = (
                int(round(candidate_solver.ObjectiveValue()))
                if status in ("OPTIMAL", "FEASIBLE")
                else None
            )
            _left = (
                max(0.0, budget_s - (time.perf_counter() - started))
                if budget_s > 0
                else 0.0
            )
            _polished = _polish_meal_bindings(
                bundle, enriched, tier, _base, _floor, wall_s=_left
            )
            if _polished is not None:
                _was_optimal = status == "OPTIMAL"
                candidate_solver, status = _polished
                if status == "OPTIMAL" and not _was_optimal:
                    # 打磨只在「钉分日」子空间里证优，不能冒称整层最优
                    status = "FEASIBLE"
        if status == "INFEASIBLE":
            return Solution(
                status="INFEASIBLE",
                wall_ms=int((time.perf_counter() - started) * 1000),
                objective_values=objective_values,
                hint_used=hint is not None,
                wall_capped=wall_capped,
                c06_yielded_to_day_plan=c06_yielded,
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
        if index == 0 and status == "OPTIMAL" and not greedy_seeded:
            # R4/R8-S4 贪心 fill incumbent 种子：tier① 证毕即种——
            # 原挂在 index==1 的 Solve 之后=死代码，tier② 大池在
            # 0.4 dtime 内无 incumbent 直接 UNKNOWN，阶梯保空前缀
            # （90 候选 all-fill 空排根因之二，live 实锤）。greedy
            # 按 tier 序落最空日，hint 仅热启动不影响确定性。
            _seed_greedy_fill_hints(bundle, enriched, solver)
            greedy_seeded = True
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
            wall_capped=wall_capped,
            c06_yielded_to_day_plan=c06_yielded,
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
        wall_capped=wall_capped,
        c06_yielded_to_day_plan=c06_yielded,
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
        # R8-S4：tier② 按池规模再定标（×n/20、上限 4×；36 候选→0.9）；
        # 墙钟随 tier② 增量微提（满载下 dtime 的墙钟换算会放大，Q3 披露）
        solve_kwargs["tier2_det"] = 0.5 * max(
            1.0, min(4.0, len(enriched.snapshot.candidates) / 20.0)
        )
        budget_s = max(budget_s, 5.5 + (solve_kwargs["tier2_det"] - 0.5))
        extra = [
            "行程规模较大，求解时间预算按 Q3 披露放宽至 %.1fs（绝不回退顺序排列）"
            % budget_s
        ]
    # 预算核算覆盖 build_model（g11 建模 ~1s 不含在 solve 内会翻预算）
    remaining_after_build = (
        max(0.15, budget_s - (_time.perf_counter() - started)) if budget_s > 0 else 0.0
    )
    solution = solve(bundle, enriched, remaining_after_build, **solve_kwargs)
    if extra and solution.disclosures is not None:
        solution.disclosures = list(solution.disclosures) + extra
    if solution.status != "INFEASIBLE":
        # R13d：budget_used_ms 记提升后总预算（F-62 收敛口径=引擎段
        # build+solve 对总预算；solve() 内部记的是扣建模后的余量，
        # 求解器吃满配额时 shadow 层的 wall（含 enrich/建模/提取）必然
        # 越线——共享机负载下 g11 刀刃误红即此）。
        solution.budget_used_ms = int(budget_s * 1000)
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
                relaxed.budget_used_ms = int(budget_s * 1000)
                return relaxed
    solution.certificate = explain_infeasibility(enriched)
    solution.budget_used_ms = int(budget_s * 1000)
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
        "c06_yielded_to_day_plan": bool(solution.c06_yielded_to_day_plan),
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
