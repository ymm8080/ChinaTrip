# -*- coding: utf-8 -*-
"""R39（2026-11-25 用户「why no restaurants is pick up at all」）。

根因：R12-F4 日预算把餐馆当普通景点填充计入 fill_mid；但餐位时刻已在
skeleton 的 150 分钟里预留，餐馆只是填进这张已留的餐卡。稠密日必去满档
吃掉整个预算后，库内高分餐馆全被压掉、餐卡全落自由卡。

覆盖：
1. 餐馆不进 fill_mid——必去满档时餐馆仍可在场；
2. 非餐馆填充仍受原闸约束（R12-F4 语义未废）；
3. 溢出日（必去自挤超容）行为不变。
"""

from __future__ import annotations

from types import SimpleNamespace

from ortools.sat.python import cp_model

from app.services.trip_solver.model.c09_c16 import _r12f_fill_yields_gate


def _cand(cid: str, category: str, *, remote: bool = False, rid=None):
    return SimpleNamespace(cid=cid, category=category, rid=rid, remote=remote)


def _build(cands, mid_by_cid, forced):
    """最小 bundle/enriched：presence 全 1/0 由 forced 钉住，其余自由。"""
    model = cp_model.CpModel()
    days = [1]
    presence = {
        (c.cid, 1): model.NewBoolVar(f"p_{c.cid}") for c in cands
    }
    for c in cands:
        if c.cid in forced:
            model.Add(presence[(c.cid, 1)] == forced[c.cid])
    tiers = {c.cid: (0, mid_by_cid[c.cid], mid_by_cid[c.cid]) for c in cands}
    bundle = SimpleNamespace(model=model, presence=presence, days=days)
    enriched = SimpleNamespace(
        snapshot=SimpleNamespace(candidates=cands), tiers=tiers
    )
    _r12f_fill_yields_gate(bundle, enriched)
    return model, presence


def test_food_not_counted_in_fill_budget_when_musts_fill_day():
    # 必去 mid=450：must_mid=450+30=480，base=240 → 720 ≤ 750（不溢出）。
    # 餐馆 mid=60：旧口径 fill_mid=60+30=90 → 720+90=810>750 被压掉；
    # 新口径餐馆不进预算 → 仍可在场。
    must = _cand("s1", "museum", rid="must-s1")
    food = _cand("f1", "food")
    model, presence = _build(
        [must, food], {"s1": 450, "f1": 60}, {"s1": 1, "f1": 1}
    )
    assert cp_model.CpSolver().Solve(model) == cp_model.OPTIMAL


def test_sight_fill_still_budgeted():
    # 非餐馆填充 mid=60 仍占预算：720+90=810>750 → 不可行（原闸不废）。
    must = _cand("s1", "museum", rid="must-s1")
    fill = _cand("v1", "museum")
    model, presence = _build(
        [must, fill], {"s1": 450, "v1": 60}, {"s1": 1, "v1": 1}
    )
    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


def test_overflow_day_exempts_budget_for_food_and_fill():
    # 必去 mid=600 → 600+30+240=870>750 溢出日；预算豁免，填充照常进场。
    must = _cand("s1", "museum", rid="must-s1")
    food = _cand("f1", "food")
    fill = _cand("v1", "museum")
    model, presence = _build(
        [must, food, fill],
        {"s1": 600, "f1": 60, "v1": 60},
        {"s1": 1, "f1": 1, "v1": 1},
    )
    assert cp_model.CpSolver().Solve(model) == cp_model.OPTIMAL


def test_no_musts_no_gate_fires():
    # 无必去 → 闸提前 return，餐馆与景点填充都自由。
    food = _cand("f1", "food")
    fill = _cand("v1", "museum")
    model, presence = _build(
        [food, fill], {"f1": 60, "v1": 60}, {"f1": 1, "v1": 1}
    )
    assert cp_model.CpSolver().Solve(model) == cp_model.OPTIMAL
