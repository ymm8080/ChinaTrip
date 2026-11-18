"""F-50 edit re-solve + F-51 pin provenance (P4).

Edit vocabulary (``DiffOp``): ``move`` (cid → day), ``retime``/``pin``
(cid, day, start → a USER pin: immovable, iron rule 19, cap-exempt),
``duration`` (cid → minutes, clamped into its tier), ``delete`` (fill →
absent; must → removed from the request, no unplaced obligation).

Semantics:
- user edits are FACTS: retime/pin become first-class C-04 pins on the
  request (cap exemption + horizon rules apply); everything else re-solves
  freely with the previous solution as hint (F-24) — deterministic (F-41);
- F-51 provenance: ``EditOutcome.user_pins`` records every user pin this
  edit created (``source: "user"``); the solver itself never moves one;
- M12/Q7 envelope: ≤ 800 ms with hint. On overrun the CURRENT plan is kept
  and a bilingual 「重排中，稍后自动更新」 disclosure is returned instead —
  interactions never block on the solver.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from .inputs.enrich import enrich
from .model.c01_c04 import build_model
from .model.solve import solve
from .types import FactSnapshot, FixedPin, Solution

EDIT_BUDGET_SECONDS = 0.8  # Q7/M12
# 编辑路径的确定性步预算：R1 目标项让 4 层全证超信封——hint 下每层
# 用小步预算取「已证最优前缀」；deterministic_time 跨机可复现，前缀
# 截断仍满足 F-41 确定性红线（这正是 M12 交互不阻塞的口径）
EDIT_TIER_DET = 0.12

RETIMING_DISCLOSURE = {
    "zh": "重排中，稍后自动更新（编辑重解超出 800ms 预算）",
    "en": "Re-optimising, will update shortly (edit re-solve over the 800ms budget)",
}


@dataclass(frozen=True)
class DiffOp:
    kind: str  # move | retime | pin | duration | delete | days
    cid: str
    days: Optional[int] = None  # kind=days: 新总天数（跨管线对齐 2026-11-18）
    day: Optional[int] = None
    start_min: Optional[int] = None
    duration_min: Optional[int] = None


@dataclass
class EditOutcome:
    solution: Solution
    ops_applied: list[DiffOp] = field(default_factory=list)
    user_pins: list[dict] = field(default_factory=list)  # F-51 provenance
    status: str = "SOLVED"
    wall_ms: int = 0
    within_edit_budget: bool = True
    disclosure: Optional[dict] = None


def _apply_days_op(
    snapshot: FactSnapshot, ops: list[DiffOp]
) -> tuple[FactSnapshot, list[DiffOp]]:
    """kind=days：改总天数（legacy _fit_plan_day_count 的模型侧对应物）。
    扩展=新天留白重解；收缩=装不下的必去诚实落 unplaced（绝不静默删）。"""
    for op in ops:
        if op.kind != "days" or not op.days or op.days < 1:
            continue
        if op.days == snapshot.request.days:
            ops = [o for o in ops if o is not op]
            continue
        snapshot = replace(
            snapshot,
            request=replace(snapshot.request, days=int(op.days)),
        )
        ops = [o for o in ops if o is not op]
        break
    return snapshot, ops


def _apply_pin_ops(
    snapshot: FactSnapshot, ops: list[DiffOp]
) -> tuple[FactSnapshot, list[DiffOp]]:
    """retime/pin → first-class C-04 pins on the request (cap-exempt, iron
    rule 19). Returns the patched snapshot + the remaining ops."""
    pins = list(snapshot.request.pins)
    remaining: list[DiffOp] = []
    for op in ops:
        if op.kind not in ("retime", "pin") or op.day is None or op.start_min is None:
            remaining.append(op)
            continue
        cand = next((c for c in snapshot.candidates if c.cid == op.cid), None)
        if cand is None:
            remaining.append(op)  # unknown cid: surface downstream honestly
            continue
        pins = [p for p in pins if p.cid != op.cid and p.rid != (cand.rid or "")]
        pins.append(
            FixedPin(rid=cand.rid or "", day=op.day, start_min=op.start_min, cid=op.cid)
        )
    if pins != list(snapshot.request.pins):
        snapshot = replace(
            snapshot, request=replace(snapshot.request, pins=tuple(pins))
        )
    return snapshot, remaining


def _apply_delete_ops(
    snapshot: FactSnapshot, ops: list[DiffOp]
) -> tuple[FactSnapshot, list[DiffOp]]:
    remaining: list[DiffOp] = []
    deleted_cids: set[str] = set()
    for op in ops:
        if op.kind != "delete":
            remaining.append(op)
            continue
        deleted_cids.add(op.cid)
    if not deleted_cids:
        return snapshot, remaining
    cands = tuple(c for c in snapshot.candidates if c.cid not in deleted_cids)
    killed_rids = {
        c.rid for c in snapshot.candidates if c.cid in deleted_cids and c.rid
    }
    musts = tuple(m for m in snapshot.request.musts if m.rid not in killed_rids)
    wishes = tuple(w for w in snapshot.request.wishes if w.rid not in killed_rids)
    snapshot = replace(
        snapshot,
        candidates=cands,
        request=replace(snapshot.request, musts=musts, wishes=wishes),
    )
    return snapshot, [op for op in remaining if op.cid not in deleted_cids]


def _apply_bundle_ops(bundle, enriched, ops: list[DiffOp]) -> list[DiffOp]:
    """move/duration become model facts on the built bundle."""
    applied: list[DiffOp] = []
    for op in ops:
        cand = next((c for c in enriched.snapshot.candidates if c.cid == op.cid), None)
        if cand is None:
            continue  # unknown cid: ignored, not silently "applied"
        if op.kind == "move" and op.day is not None:
            for day in bundle.days:
                lit = bundle.presence.get((op.cid, day))
                if lit is None:
                    continue
                bundle.model.Add(lit == (1 if day == op.day else 0))
            applied.append(op)
        elif op.kind == "duration" and op.duration_min is not None:
            low, _typ, high, _clamped = enriched.tiers[op.cid]
            target = max(low, min(high, int(op.duration_min)))
            bundle.model.Add(bundle.dur[op.cid] == target)
            applied.append(op)
    return applied


def edit_resolve(
    snapshot: FactSnapshot,
    previous: Optional[Solution],
    ops: list[DiffOp],
    *,
    budget_s: float = 3.0,
    edit_budget_s: float = EDIT_BUDGET_SECONDS,
    _solve: Optional[Callable] = None,
) -> EditOutcome:
    """Apply user edits and re-solve with the previous solution as hint."""
    solve_fn = _solve or solve
    started = time.perf_counter()

    pin_ops = [op for op in ops if op.kind in ("retime", "pin")]
    snapshot, ops = _apply_days_op(snapshot, ops)
    snapshot, ops = _apply_pin_ops(snapshot, ops)
    snapshot, ops = _apply_delete_ops(snapshot, ops)

    user_pins = [
        {
            "cid": op.cid,
            "day": op.day,
            "start_min": op.start_min,
            "source": "user",  # F-51: the solver never moves these
        }
        for op in pin_ops
    ]

    enriched = enrich(snapshot)
    bundle = build_model(enriched)
    applied = _apply_bundle_ops(bundle, enriched, ops)

    solution = solve_fn(
        bundle, enriched, budget_s, hint=previous, tier_det=EDIT_TIER_DET
    )
    wall_ms = int((time.perf_counter() - started) * 1000)
    within = wall_ms <= int(edit_budget_s * 1000)

    if not within and previous is not None:
        # M12/Q7: never block the interaction — keep the current plan,
        # disclose, let the caller retry in the background.
        return EditOutcome(
            solution=previous,
            ops_applied=[],
            user_pins=user_pins,
            status="RETIMING",
            wall_ms=wall_ms,
            within_edit_budget=False,
            disclosure=dict(RETIMING_DISCLOSURE),
        )

    return EditOutcome(
        solution=solution,
        ops_applied=[*pin_ops, *applied],
        user_pins=user_pins,
        status=solution.status,
        wall_ms=wall_ms,
        within_edit_budget=within,
    )
