"""F-26 infeasibility certificates + unplaced reason codes (P1-E).

Reason codes are pure static analysis over the enriched snapshot -- no
extra solves, fully deterministic. Codes attach to ``unplaced`` entries
(``reason_codes`` + rendered ``reason``) and to ``Solution.certificate``
for terminal INFEASIBLE. Every code's bilingual text lives in
``trip_solver/disclosure_templates.json`` (audit M13: 100% coverage of
emitted codes, asserted in tests).
"""

from __future__ import annotations

import io
import json
import os
from typing import TYPE_CHECKING, Any, Optional

from .c01_c04 import closed_weekdays, day_date
from .vars import DAY_END_MINUTES, DAY_START_MINUTES

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot

_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "disclosure_templates.json",
)
_TEMPLATES: Optional[dict[str, dict[str, dict[str, str]]]] = None


def load_templates() -> dict[str, dict[str, dict[str, str]]]:
    global _TEMPLATES
    if _TEMPLATES is None:
        with io.open(_TEMPLATE_PATH, "r", encoding="utf-8") as fh:
            _TEMPLATES = json.load(fh)
    return _TEMPLATES


def render_reason(
    code: str,
    lang: str = "zh",
    family: str = "certificate_reasons",
    **fields: Any,
) -> str:
    """Bilingual text for a reason code; ``format`` with field facts."""
    entry = load_templates().get(family, {}).get(code)
    if entry is None:
        raise KeyError("disclosure template missing for %s/%s" % (family, code))
    text = entry.get(lang) or entry["en"]
    return text.format(**fields) if fields else text


# The classifier literals below are the single source of truth; the
# M13 coverage test asserts the TEMPLATES cover exactly this set
# (non-circular: this set never reads the templates).
EMITTED_CODES = frozenset(
    {
        "window_duration_conflict",
        "entry_cap_conflict",
        "pin_conflict",
        "remote_exclusive_conflict",
        "family_day_conflict",
        "day_capacity_conflict",
        "no_seatable_day",
    }
)


def emitted_codes() -> set[str]:
    """Every code this module can emit (audit M13)."""
    return set(EMITTED_CODES)


def _dur_range(enriched: "EnrichedSnapshot", cand) -> tuple[int, int]:
    tier = enriched.tiers.get(cand.cid)
    if tier is not None:
        return int(tier[0]), int(tier[2])
    d = int(cand.suggested_duration_min or 0)
    return d, d


def _seatable_days(enriched: "EnrichedSnapshot", cand) -> list[int]:
    """Days where the candidate could sit ALONE (C-01/C-02 approximation;
    same first-window reading the model uses)."""
    snapshot = enriched.snapshot
    window = enriched.windows.get(cand.cid)
    dmin, _dmax = _dur_range(enriched, cand)
    cap = enriched.cap(cand.cid)
    closed = closed_weekdays(cand.opening_hours)
    ok: list[int] = []
    for day in range(1, snapshot.request.days + 1):
        day_dt = day_date(snapshot.request.start_date, day)
        if day_dt is not None and day_dt.weekday() in closed:
            continue
        lo = DAY_START_MINUTES
        hi = 23 * 60 if cand.best_visit_time == "show" else DAY_END_MINUTES
        if window is not None:
            lo = max(lo, window[0])
            hi = min(hi, window[1])
        latest_start = hi - dmin
        cap_bound = cap if cap is not None else latest_start
        if min(latest_start, cap_bound) >= lo:
            ok.append(day)
    return ok


def _pin_conflict(enriched: "EnrichedSnapshot", rid: str) -> Optional[str]:
    """A real same-day interval overlap between two pins (typ durations),
    not mere proximity -- adjacent pins are legal."""
    snapshot = enriched.snapshot
    pins = list(getattr(snapshot.request, "pins", ()) or ())
    mine = [p for p in pins if p.rid == rid]
    if not mine:
        return None
    dur_by_rid: dict[str, int] = {}
    for cand in snapshot.candidates:
        if not cand.rid:
            continue
        tier = enriched.tiers.get(cand.cid)
        dur_by_rid[cand.rid] = (
            int(tier[1]) if tier else int(cand.suggested_duration_min or 60)
        )
    for p in mine:
        pd = dur_by_rid.get(rid, 60)
        for q in pins:
            if q.rid == rid or q.day != p.day:
                continue
            qd = dur_by_rid.get(q.rid, 60)
            if p.start_min < q.start_min + qd and q.start_min < p.start_min + pd:
                return "day %d @ %02d:%02d vs day %d @ %02d:%02d" % (
                    p.day,
                    p.start_min // 60,
                    p.start_min % 60,
                    q.day,
                    q.start_min // 60,
                    q.start_min % 60,
                )
    return None


def _pin_outside_window(enriched: "EnrichedSnapshot", cands: list) -> bool:
    """A pin whose fixed start cannot satisfy the item's own C-01/C-02
    band makes the model structurally infeasible (pins are never
    relaxed, F-25)."""
    snapshot = enriched.snapshot
    pins = list(getattr(snapshot.request, "pins", ()) or ())
    by_rid = {c.rid: c for c in cands}
    for p in pins:
        cand = by_rid.get(p.rid)
        if cand is None:
            continue
        dmin, _dmax = _dur_range(enriched, cand)
        window = enriched.windows.get(cand.cid)
        # 铁律19: pins are exempt from the day-start clamp (c01_c04).
        lo = window[0] if window is not None else 0
        hi = 23 * 60 if cand.best_visit_time == "show" else DAY_END_MINUTES
        if window is not None:
            lo = max(lo, window[0])
            hi = min(hi, window[1])
        latest = hi - dmin
        cap = enriched.cap(cand.cid)
        if cap is not None:
            latest = min(latest, cap)
        if p.start_min < lo or p.start_min > latest:
            return True
    return False


def classify_requested(enriched: "EnrichedSnapshot", rid: str) -> list[str]:
    """Ordered reason codes for a requested item that cannot be seated."""
    snapshot = enriched.snapshot
    cands = [c for c in snapshot.candidates if c.rid == rid]
    if not cands:
        return ["no_seatable_day"]
    codes: list[str] = []
    clash = _pin_conflict(enriched, rid)
    if clash:
        codes.append("pin_conflict")
        return codes
    if _pin_outside_window(enriched, cands):
        codes.append("pin_conflict")
        return codes
    seatable: set[int] = set()
    for cand in cands:
        seatable |= set(_seatable_days(enriched, cand))
    if not seatable:
        window_fits = any(
            enriched.windows.get(c.cid) is None
            or (
                enriched.windows[c.cid][1] - enriched.windows[c.cid][0]
                >= _dur_range(enriched, c)[0]
            )
            for c in cands
        )
        cap_binds = any(enriched.cap(c.cid) is not None for c in cands)
        if not window_fits:
            codes.append("window_duration_conflict")
        elif cap_binds:
            codes.append("entry_cap_conflict")
        else:
            codes.append("no_seatable_day")
        return codes
    # Seatable alone but not inside the full model: combination blockers.
    days = snapshot.request.days
    remote_clusters = {
        c.poi_id or c.cid
        for c in snapshot.candidates
        if c.rid and (c.poi_id or c.cid) in enriched.access_by_poi
    }
    remote_rids = {
        c.rid
        for c in snapshot.candidates
        if c.rid and (c.poi_id or c.cid) in enriched.access_by_poi
    }
    # same-cluster remotes may co-locate (C-06): only distinct
    # clusters consume exclusive days
    if rid in remote_rids and len(remote_clusters) > days:
        codes.append("remote_exclusive_conflict")
        return codes
    from .c09_c16 import DAY_LOAD_BUDGET_MINUTES

    families: dict[str, int] = {}
    fam_by_rid: dict[str, str] = {}
    for req in list(snapshot.request.musts) + list(snapshot.request.wishes):
        fam = getattr(req, "family_id", None)
        if not fam:
            continue
        fam_by_rid[req.rid] = fam
        for c in snapshot.candidates:
            if c.rid == req.rid:
                families[fam] = families.get(fam, 0) + _dur_range(enriched, c)[0]
    fam = fam_by_rid.get(rid)
    if fam and families.get(fam, 0) > DAY_LOAD_BUDGET_MINUTES:
        codes.append("family_day_conflict")
        return codes
    codes.append("day_capacity_conflict")
    return codes


def unplaced_reasons(enriched: "EnrichedSnapshot", unplaced: list[dict]) -> list[dict]:
    """Attach F-26 reason codes + rendered zh reason to unplaced entries."""
    for entry in unplaced:
        rid = str(entry.get("rid") or "")
        if not rid:
            continue
        codes = classify_requested(enriched, rid)
        entry["reason_codes"] = codes
        entry["reason"] = "；".join(
            render_reason(code, "zh", name=str(entry.get("name") or rid))
            for code in codes
        )
    return unplaced


def explain_infeasibility(enriched: "EnrichedSnapshot") -> list[dict]:
    """Terminal-INFEASIBLE certificate: one structured entry per blocker.
    The model is infeasible as a whole, so every requested item gets its
    classification plus pin-clash evidence where present."""
    snapshot = enriched.snapshot
    out: list[dict] = []
    for req in list(snapshot.request.musts) + list(snapshot.request.wishes):
        codes = classify_requested(enriched, req.rid)
        clash = _pin_conflict(enriched, req.rid)
        detail = clash or ""
        for code in codes:
            out.append(
                {
                    "code": code,
                    "rid": req.rid,
                    "name": req.name,
                    "detail": (
                        render_reason(code, "zh", name=req.name)
                        + ("（%s）" % clash if clash else "")
                    ),
                    "evidence": detail,
                }
            )
    if not out:
        out.append(
            {
                "code": "no_seatable_day",
                "rid": None,
                "name": None,
                "detail": render_reason("no_seatable_day", "zh", name="行程"),
                "evidence": "",
            }
        )
    return out
