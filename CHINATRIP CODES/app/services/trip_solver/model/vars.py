"""F-20 variable bundle: optional presence per (candidate, day), duration
inside its tier, and the requested→unplaced hard link that makes silent
loss unrepresentable (B-01).

Global horizon: minutes since midnight, [DAY_START, DAY_END] — ported from
solver.DAY_START/DAY_END (2026-11-14 拍板 08:30; transports/flag sessions
are objective fixed windows, handled via C-04 pins, not this horizon).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot

DAY_START_MINUTES = 8 * 60 + 30
DAY_END_MINUTES = 21 * 60
MINUTES_PER_DAY = 24 * 60


@dataclass
class VarBundle:
    model: cp_model.CpModel
    days: list[int]
    presence: dict[tuple[str, int], "cp_model.IntVar"]
    start: dict[tuple[str, int], "cp_model.IntVar"]
    dur: dict[str, "cp_model.IntVar"]
    unplaced: dict[str, "cp_model.IntVar"]
    rid_cids: dict[str, list[str]] = field(default_factory=dict)
    cid_day_list: list[tuple[str, int]] = field(default_factory=list)
    dep_vars: dict = field(default_factory=dict)  # C-08 outbound departures
    ret_vars: dict = field(default_factory=dict)  # C-08 return departures
    arrival_vars: dict = field(default_factory=dict)  # C-08 access arrival
    active_dep_vars: dict = field(default_factory=dict)  # F-23 early access
    active_ret_vars: dict = field(default_factory=dict)
    active_start: dict[tuple[str, int], "cp_model.IntVar"] = field(default_factory=dict)
    active_dur: dict[tuple[str, int], "cp_model.IntVar"] = field(default_factory=dict)
    active_end: dict[tuple[str, int], "cp_model.IntVar"] = field(default_factory=dict)
    meal_vars: dict = field(default_factory=dict)  # C-09/F-22 intervals
    # R12-H22：余量槽闸豁免布尔（C-02 建、C-06 约束——返程后那
    # 一个设计位才许 lift 入场闸）
    cap_escapes: dict = field(default_factory=dict)
    hotel_vars: dict = field(default_factory=dict)  # C-13 intervals
    day_active: dict[int, "cp_model.IntVar"] = field(default_factory=dict)
    day_end_vars: dict[int, "cp_model.IntVar"] = field(default_factory=dict)
    travel_terms: list = field(default_factory=list)  # F-23 tier ③
    fill_gates: dict[str, "cp_model.IntVar"] = field(
        default_factory=dict
    )  # tier-① fill-free assumption gates
    meal_bound: dict = field(default_factory=dict)  # R8-S2b 真餐厅 any-槽选择


def define_variables(enriched: "EnrichedSnapshot") -> VarBundle:
    snapshot = enriched.snapshot
    model = cp_model.CpModel()
    days = list(range(1, snapshot.request.days + 1))

    presence: dict[tuple[str, int], object] = {}
    start: dict[tuple[str, int], object] = {}
    dur: dict[str, object] = {}
    rid_cids: dict[str, list[str]] = {}
    cid_day_list: list[tuple[str, int]] = []
    active_start: dict[tuple[str, int], object] = {}
    active_dur: dict[tuple[str, int], object] = {}
    active_end: dict[tuple[str, int], object] = {}
    fill_gates: dict[str, object] = {}

    for cand in snapshot.candidates:
        if cand.rid:
            rid_cids.setdefault(cand.rid, []).append(cand.cid)
        tier = enriched.tiers[cand.cid]
        dur[cand.cid] = model.NewIntVar(tier[0], tier[2], "dur_%s" % cand.cid)
        for day in days:
            lit = model.NewBoolVar("p_%s_%d" % (cand.cid, day))
            st = model.NewIntVar(0, MINUTES_PER_DAY, "s_%s_%d" % (cand.cid, day))
            en = model.NewIntVar(
                0, MINUTES_PER_DAY + tier[2], "e_%s_%d" % (cand.cid, day)
            )
            model.NewOptionalIntervalVar(
                st, dur[cand.cid], en, lit, "iv_%s_%d" % (cand.cid, day)
            )
            presence[(cand.cid, day)] = lit
            start[(cand.cid, day)] = st
            cid_day_list.append((cand.cid, day))

            ast = model.NewIntVar(0, MINUTES_PER_DAY, "as_%s_%d" % (cand.cid, day))
            adu = model.NewIntVar(0, tier[2], "ad_%s_%d" % (cand.cid, day))
            aen = model.NewIntVar(
                0, MINUTES_PER_DAY + tier[2], "ae_%s_%d" % (cand.cid, day)
            )
            model.Add(ast == st).OnlyEnforceIf(lit)
            model.Add(ast == 0).OnlyEnforceIf(lit.Not())
            model.Add(adu == dur[cand.cid]).OnlyEnforceIf(lit)
            model.Add(adu == 0).OnlyEnforceIf(lit.Not())
            model.Add(aen == st + dur[cand.cid]).OnlyEnforceIf(lit)
            model.Add(aen == 0).OnlyEnforceIf(lit.Not())
            active_start[(cand.cid, day)] = ast
            active_dur[(cand.cid, day)] = adu
            active_end[(cand.cid, day)] = aen

    unplaced: dict[str, object] = {}
    for req in list(snapshot.request.musts) + list(snapshot.request.wishes):
        cids = rid_cids.get(req.rid) or []
        lit = model.NewBoolVar("u_%s" % req.rid)
        unplaced[req.rid] = lit
        placed = sum(presence[(cid, d)] for cid in cids for d in days) if cids else 0
        if req.kind == "must":
            # requested ∧ ¬presence → unplaced_var : sum + unplaced == 1
            model.Add(placed + lit == 1)
        else:
            # Wishes are lower-weight in F-23 tier ①, not silently droppable:
            # an unscheduled wish must surface through its unplaced variable.
            model.Add(placed + lit == 1)

    for cand in snapshot.candidates:
        if cand.rid:
            continue  # governed by the requested link above
        total = sum(presence[(cand.cid, d)] for d in days)
        model.Add(total <= 1)  # fill candidates: at most one day
        gate = model.NewBoolVar("fill_gate_%s" % cand.cid)
        for day in days:
            model.Add(presence[(cand.cid, day)] <= gate)
        fill_gates[cand.cid] = gate

    return VarBundle(
        model=model,
        days=days,
        presence=presence,
        start=start,
        dur=dur,
        unplaced=unplaced,
        rid_cids=rid_cids,
        cid_day_list=cid_day_list,
        active_start=active_start,
        active_dur=active_dur,
        active_end=active_end,
        fill_gates=fill_gates,
    )
