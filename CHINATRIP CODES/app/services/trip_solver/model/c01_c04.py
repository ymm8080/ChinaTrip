"""C-01..C-04 constraints + tier-① objective (P1-C1).

C-01 opening windows + closed weekdays — window from the F-12 first-window
approximation; 周X关闭 parses from the hours text.
C-02 entry caps (990/930, exemptions resolved upstream in F-12).
C-03 pairwise travel disjunction: if two candidates share a day, one must
finish + travel before the other starts (matrix lookup, default 45).
C-04 pins (iron rule 19: exact day + start) and day1_start horizon shift.

Objective (P1-C1 minimal, tier ① only): minimise sum(unplaced × importance).
F-23 full lexicographic objectives arrive in P1-D.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

from ..inputs.travel import lookup
from .vars import DAY_END_MINUTES, DAY_START_MINUTES, VarBundle, define_variables

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot

_CLOSED_RE = re.compile(r"周([一二三四五六日天])关闭")
_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def closed_weekdays(hours_text: str | None) -> frozenset[int]:
    return frozenset(
        _WEEKDAYS[m.group(1)] for m in _CLOSED_RE.finditer(hours_text or "")
    )


def day_date(start_date: str | None, day: int) -> date | None:
    if not start_date:
        return None
    try:
        base = date.fromisoformat(start_date)
    except ValueError:
        return None
    return base + timedelta(days=day - 1)


def add_c01_windows(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    model = bundle.model
    for cand in snapshot.candidates:
        window = enriched.windows.get(cand.cid)
        closed = closed_weekdays(cand.opening_hours)
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            start = bundle.start[(cand.cid, day)]
            day_dt = day_date(snapshot.request.start_date, day)
            if day_dt is not None and day_dt.weekday() in closed:
                model.Add(lit == 0)  # 闭馆日不可排（C-01）
                continue
            lo = DAY_START_MINUTES
            hi = DAY_END_MINUTES
            if window is not None:
                lo = max(lo, window[0])
                hi = min(hi, window[1])
            model.Add(start >= lo).OnlyEnforceIf(lit)
            model.Add(start + bundle.dur[cand.cid] <= hi).OnlyEnforceIf(lit)


def add_c02_caps(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    for cand in enriched.snapshot.candidates:
        cap, _reason = enriched.caps.get(cand.cid, (None, "unknown"))
        if cap is None:
            continue
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            bundle.model.Add(bundle.start[(cand.cid, day)] <= cap).OnlyEnforceIf(lit)


def add_c03_travel(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    candidates = enriched.snapshot.candidates
    keys = {c.cid: (c.poi_id or c.cid) for c in candidates}
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            ab = lookup(enriched.matrix, keys[a.cid], keys[b.cid])
            ba = lookup(enriched.matrix, keys[b.cid], keys[a.cid])
            for day in bundle.days:
                pa = bundle.presence[(a.cid, day)]
                pb = bundle.presence[(b.cid, day)]
                if pa is pb:
                    continue
                order = bundle.model.NewBoolVar("o_%s_%s_%d" % (a.cid, b.cid, day))
                sa = bundle.start[(a.cid, day)]
                sb = bundle.start[(b.cid, day)]
                bundle.model.Add(sb >= sa + bundle.dur[a.cid] + ab).OnlyEnforceIf(
                    [pa, pb, order]
                )
                bundle.model.Add(sa >= sb + bundle.dur[b.cid] + ba).OnlyEnforceIf(
                    [pa, pb, order.Not()]
                )


def add_c04_pins(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    request = enriched.snapshot.request
    for pin in getattr(request, "pins", ()) or ():
        cids = bundle.rid_cids.get(pin.rid) or ([pin.cid] if pin.cid else [])
        if not cids:
            raise ValueError("pin %r references no candidate" % pin.rid)
        for cid in cids:
            for day in bundle.days:
                lit = bundle.presence[(cid, day)]
                if day == pin.day:
                    bundle.model.Add(lit == 1)
                    # iron rule 19: the pin's clock is objective, not horizon-bound
                    bundle.model.Add(bundle.start[(cid, day)] == pin.start_min)
                else:
                    bundle.model.Add(lit == 0)
    if request.day1_start:
        hh, mm = request.day1_start.split(":")
        floor = int(hh) * 60 + int(mm)
        for cand in enriched.snapshot.candidates:
            lit = bundle.presence[(cand.cid, 1)]
            if 1 in bundle.days:
                bundle.model.Add(bundle.start[(cand.cid, 1)] >= floor).OnlyEnforceIf(
                    lit
                )


def add_objective(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    weight = {r.rid: max(1, r.importance) for r in snapshot.request.musts}
    weight.update({r.rid: 1 for r in snapshot.request.wishes})
    terms = [bundle.unplaced[rid] * weight.get(rid, 1) for rid in bundle.unplaced]
    if terms:
        bundle.model.Minimize(sum(terms))


def build_model(enriched: "EnrichedSnapshot") -> VarBundle:
    bundle = define_variables(enriched)
    add_c01_windows(bundle, enriched)
    add_c02_caps(bundle, enriched)
    add_c03_travel(bundle, enriched)
    add_c04_pins(bundle, enriched)
    add_objective(bundle, enriched)
    return bundle
