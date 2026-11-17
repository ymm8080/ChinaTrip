"""C-05..C-08 constraints (P1-C2).

C-05 endpoint days: arrival/departure days exist ONLY with a timed intercity
leg (438bcfa). arrival_time → day-1 starts ≥ arrival+ARRIVAL_FLOOR_MINUTES;
departure_time → last day ends ≤ dep-DEPARTURE_BUFFER_MINUTES. No transport
info = full day (nothing added).

C-06 remote-day exclusivity — refined by the 24379abd hotfix evidence:
on a day holding a remote item (access profile present), other requested
candidates are allowed ONLY as ≤1 city morning anchor (start ≤ 10:30,
before the outbound access leg); unrequested fill is never placed there
(C-15 effect). Same-cluster remote items are unconstrained. A naive
"same-cluster or empty" rule would forbid the E-1 morning anchor, so it is
NOT the rule — the morning anchor is the exception that makes 天安门 →
慕田峪 legal.

C-07 city coherence: candidates with different `city` values never share a
day (single-city snapshots are unconstrained). Multi-city order itself is
an intent-layer input (Q6).

C-08 access legs as intervals (conservative, same semantics as the legacy
hotfix): for a remote candidate with an access profile, the visit start is
pinned to a timetable departure: start == dep + ride + last_mile; a
morning anchor must finish + taxi before dep; the return leg starts ≥
visit.end + RETURN_BUFFER and arrives back in the city. Pairs involving a
profiled remote candidate are excluded from the generic C-03 matrix
disjunction (the profile replaces it). Post-return non-cluster items are
already impossible by C-06, so no extra after-return ordering is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from ..inputs.access import hhmm_to_min
from .vars import VarBundle

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot

ARRIVAL_FLOOR_MINUTES = 150  # 落地首停 ≥ 落地 2.5h（legacy ARRIVAL_STOP_FLOOR）
DEPARTURE_BUFFER_MINUTES = 90
MORNING_ANCHOR_CAP = 10 * 60 + 30  # 晨锚最迟 10:30
RETURN_BUFFER_MINUTES = 8
DEFAULT_GATEWAY_TAXI_MINUTES = 15


def _hhmm(text: str | None) -> int | None:
    if not text:
        return None
    return hhmm_to_min(text)


def _profile_keys(enriched: "EnrichedSnapshot") -> set[str]:
    return set(enriched.access_by_poi.keys())


def add_c05_endpoints(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    request = enriched.snapshot.request
    arrival = _hhmm(getattr(request, "arrival_time", None))
    departure = _hhmm(getattr(request, "departure_time", None))
    if arrival is not None and bundle.days:
        floor = arrival + ARRIVAL_FLOOR_MINUTES
        for cand in enriched.snapshot.candidates:
            lit = bundle.presence[(cand.cid, bundle.days[0])]
            bundle.model.Add(
                bundle.start[(cand.cid, bundle.days[0])] >= floor
            ).OnlyEnforceIf(lit)
    if departure is not None and bundle.days:
        last = bundle.days[-1]
        cap = departure - DEPARTURE_BUFFER_MINUTES
        for cand in enriched.snapshot.candidates:
            lit = bundle.presence[(cand.cid, last)]
            bundle.model.Add(
                bundle.start[(cand.cid, last)] + bundle.dur[cand.cid] <= cap
            ).OnlyEnforceIf(lit)


def add_c06_remote_exclusivity(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    profiled = _profile_keys(enriched)
    remote_cids = [
        c.cid for c in snapshot.candidates if (c.poi_id or c.cid) in profiled
    ]
    if not remote_cids:
        return
    for day in bundle.days:
        for rid_cid in remote_cids:
            lr = bundle.presence[(rid_cid, day)]
            anchors: list = []
            for other in snapshot.candidates:
                if other.cid == rid_cid:
                    continue
                if (other.poi_id or other.cid) in profiled:
                    continue  # same remote cluster: allowed
                lit = bundle.presence[(other.cid, day)]
                if not other.rid:
                    # 远郊日不放非请求补点（C-15 效果）
                    bundle.model.Add(lit == 0).OnlyEnforceIf(lr)
                    continue
                anchors.append(lit)
                bundle.model.Add(
                    bundle.start[(other.cid, day)] <= MORNING_ANCHOR_CAP
                ).OnlyEnforceIf([lit, lr])
            if anchors:
                bundle.model.Add(sum(anchors) <= 1).OnlyEnforceIf(lr)


def add_c07_city_coherence(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    candidates = enriched.snapshot.candidates
    for i, a in enumerate(candidates):
        if not getattr(a, "city", None):
            continue
        for b in candidates[i + 1 :]:
            if not getattr(b, "city", None) or a.city == b.city:
                continue
            for day in bundle.days:
                bundle.model.Add(
                    bundle.presence[(a.cid, day)] + bundle.presence[(b.cid, day)] <= 1
                )


def add_c08_access(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    profiled = _profile_keys(enriched)
    for cand in snapshot.candidates:
        key = cand.poi_id or cand.cid
        profile = enriched.access_by_poi.get(key)
        if profile is None:
            continue
        deps = [hhmm_to_min(d) for d in profile.departures]
        rets = [hhmm_to_min(d) for d in profile.returns]
        if not deps:
            continue
        ride = int(profile.ride_minutes)
        last_mile = int(profile.last_mile_minutes or 0)
        taxi = int(getattr(profile, "taxi_minutes", 0) or 0)
        taxi = taxi or DEFAULT_GATEWAY_TAXI_MINUTES
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            dep = bundle.model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(deps), "dep_%s_%d" % (cand.cid, day)
            )
            bundle.dep_vars[(cand.cid, day)] = dep
            # 卡时刻=班次时刻：start == dep + ride + last_mile
            bundle.model.Add(
                bundle.start[(cand.cid, day)] == dep + ride + last_mile
            ).OnlyEnforceIf(lit)
            # 晨锚必须先结束+打车，才允许赶这一班（C-06 的晨锚例外）
            for other in snapshot.candidates:
                if other.cid == cand.cid or not other.rid:
                    continue
                if (other.poi_id or other.cid) in profiled:
                    continue
                lo = bundle.presence[(other.cid, day)]
                bundle.model.Add(
                    dep >= bundle.start[(other.cid, day)] + bundle.dur[other.cid] + taxi
                ).OnlyEnforceIf([lit, lo])
            if not rets:
                continue
            ret = bundle.model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(rets), "ret_%s_%d" % (cand.cid, day)
            )
            bundle.ret_vars[(cand.cid, day)] = ret
            # 返程腿：散场+缓冲 → 回城（回城后的非簇件已被 C-06 禁掉）
            bundle.model.Add(
                ret
                >= bundle.start[(cand.cid, day)]
                + bundle.dur[cand.cid]
                + RETURN_BUFFER_MINUTES
            ).OnlyEnforceIf(lit)


def extract_access_legs(
    bundle: VarBundle, enriched: "EnrichedSnapshot", solver
) -> list[dict]:
    """Read chosen departures back out for Solution.access_legs (card ≡ leg)."""
    out: list[dict] = []
    snapshot = enriched.snapshot
    for cand in snapshot.candidates:
        key = cand.poi_id or cand.cid
        profile = enriched.access_by_poi.get(key)
        if profile is None:
            continue
        ride = int(profile.ride_minutes)
        last_mile = int(profile.last_mile_minutes or 0)
        for day in bundle.days:
            if not solver.Value(bundle.presence[(cand.cid, day)]):
                continue
            dep_var = bundle.dep_vars.get((cand.cid, day))
            if dep_var is None:
                continue
            dep_min = solver.Value(dep_var)
            ret_var = bundle.ret_vars.get((cand.cid, day))
            ret_min = solver.Value(ret_var) if ret_var is not None else None
            start = solver.Value(bundle.start[(cand.cid, day)])
            dur = solver.Value(bundle.dur[cand.cid])
            out.append(
                {
                    "cid": cand.cid,
                    "day": day,
                    "gateway": profile.gateway,
                    "depart_min": dep_min,
                    "arrive_poi_min": start,
                    "visit_end_min": start + dur,
                    "return_depart_min": ret_min,
                    "arrive_city_min": (
                        ret_min + ride + last_mile if ret_min is not None else None
                    ),
                }
            )
    return out
