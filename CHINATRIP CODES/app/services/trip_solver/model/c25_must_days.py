# -*- coding: utf-8 -*-
"""C-25 文本日块（R25c：KEEP=日内固定、整天可换）。

用户拍板（2026-11-23 夜）：KEEP 的日内景点选择固定、顺序固定；但整天
（第 N 天那一组）可以按天气（室内/室外优先）换日——REPLAN 则不建任何块约束。

机制：每个写明的天=1 块。block_day(g,d) 为块的归日变量：
- 块至多占一天；成员 presence(c,d) ≤ block_day(g,d)（成员只能在块的当天，
  容量不足时可单独缺席→披露，不拖垮整块）；block_day → 至少一名
  成员在场（防空块占天）；
- 顺序：块内相邻成员同时在场 → start(b) ≥ start(a)+dur(a)（不拆序、不插队）；
- 归日软偏好：期望回写的天——但 preference 层（天气/质量）在更早的词典序
  先锁定，天气更优时块自然换天；平手时由 objectives._day_hint 层回写的天。
"""

from __future__ import annotations


def has_user_day_blocks(request) -> bool:
    """True when the user authored explicit per-day must-visit groups.

    Mirrors the activation condition of :func:`add_c25_day_blocks`: a must
    carrying an in-range integer ``day_hint`` becomes a hard same-day block.
    Other heuristics that would conflict with such a block (notably C-06
    remote-day exclusivity) must yield to it -- otherwise the user's own
    grouping turns infeasible and the min-drop ladder discards must-visits.
    """
    days_total = int(getattr(request, "days", 0) or 0)
    if days_total <= 0:
        return False
    return any(
        isinstance(getattr(req, "day_hint", None), int)
        and 1 <= req.day_hint <= days_total
        for req in (getattr(request, "musts", ()) or ())
    )


def add_c25_day_blocks(bundle, enriched) -> None:
    request = enriched.snapshot.request
    days_total = int(getattr(request, "days", 0) or 0)
    if days_total <= 0:
        return
    hints: dict[str, int] = {}
    order: list[str] = []
    for req in getattr(request, "musts", ()) or ():
        hint = getattr(req, "day_hint", None)
        if isinstance(hint, int) and 1 <= hint <= days_total:
            hints[str(req.rid)] = hint
            order.append(str(req.rid))
    if not hints:
        return
    groups: dict[int, list[str]] = {}
    for rid in order:
        groups.setdefault(hints[rid], []).append(rid)
    cand_by_rid: dict[str, list] = {}
    for cand in enriched.snapshot.candidates:
        if cand.kind == "requested" and cand.rid:
            cand_by_rid.setdefault(str(cand.rid), []).append(cand)
    block_vars: dict[tuple[int, int], object] = {}
    block_meta: list[tuple[int, list[str]]] = []
    for hint_day, rids in groups.items():
        members = [c for rid in rids for c in cand_by_rid.get(rid, [])]
        if not members:
            continue
        per_day = {
            int(d): bundle.model.NewBoolVar("c25_block_%d_%d" % (hint_day, int(d)))
            for d in bundle.days
        }
        bundle.model.Add(sum(per_day.values()) <= 1)
        for cand in members:
            for d in bundle.days:
                bundle.model.Add(bundle.presence[(cand.cid, int(d))] <= per_day[int(d)])
        for d in bundle.days:
            lits = [bundle.presence[(cand.cid, int(d))] for cand in members]
            bundle.model.Add(per_day[int(d)] <= sum(lits))
        for a_rid, b_rid in zip(rids, rids[1:]):
            cand_a = (cand_by_rid.get(a_rid) or [None])[0]
            cand_b = (cand_by_rid.get(b_rid) or [None])[0]
            if cand_a is None or cand_b is None:
                continue
            for d in bundle.days:
                dd = int(d)
                bundle.model.Add(
                    bundle.start[(cand_b.cid, dd)]
                    >= bundle.start[(cand_a.cid, dd)] + bundle.dur[cand_a.cid]
                ).OnlyEnforceIf(
                    [
                        bundle.presence[(cand_a.cid, dd)],
                        bundle.presence[(cand_b.cid, dd)],
                    ]
                )
        block_meta.append((int(hint_day), list(rids)))
        for dd, lit in per_day.items():
            block_vars[(int(hint_day), int(dd))] = lit
    bundle.c25_day_blocks = {
        "vars": block_vars,
        "groups": block_meta,
        "hints": hints,
    }


def day_hint_terms(bundle) -> list:
    """归日软偏好项：块落在非「写的天」每天记 1。"""
    meta = getattr(bundle, "c25_day_blocks", None) or {}
    vars_ = meta.get("vars") or {}
    terms = []
    for (hint_day, d), lit in vars_.items():
        if int(d) != int(hint_day):
            terms.append(lit)
    return terms
