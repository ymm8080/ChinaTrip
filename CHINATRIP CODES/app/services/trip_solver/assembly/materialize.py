"""F-30 materialise_plan: Solution -> ItineraryPlan.

Cards start/end come from solution intervals; access-leg fields and the
independent return card come from the *same* F-14 intervals the model
constrained (card == leg by construction — the legacy
``attach_return_cards`` reads annotate_legs' display chain instead, so
assembly synthesises the return card from the authoritative solution
intervals directly). A requested item not present becomes an
``unplaced`` entry with reason codes + bilingual reason; an untimed
requested card cannot exist by type (SolutionItem always carries
minutes).
"""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING, Optional

from ...itinerary.item_ids import ensure_unique_item_ids
from ...itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    UnplacedCandidate,
    VisitItem,
)
from ..snapshot import snapshot_hash

if TYPE_CHECKING:  # pragma: no cover
    from ..types import FactSnapshot, Solution

RETURN_CARD_PREFIX = "access-return-"
RETURN_HINT = {
    "zh": "游玩结束后按返程班次回城（独立回城卡）",
    "en": "Return shuttle after the visit (separate return card)",
}


def _hhmm(minutes: int) -> time:
    return time(minutes // 60 % 24, minutes % 60)


def _base_city(snapshot: "FactSnapshot", day: int) -> str:
    cities = list(snapshot.request.cities) or ["?"]
    if len(cities) == 1:
        return cities[0]
    return cities[min(day - 1, len(cities) - 1)]


def _location(cand) -> Optional[GeoPoint]:
    if cand.lon is None or cand.lat is None:
        return None
    return GeoPoint(lon=float(cand.lon), lat=float(cand.lat))


def compact_days(plan, snapshot):
    """R2 deterministic day compaction (timing-only, barrier-aware).

    Movable cards pull left inside their windows; FIXED cards -- system
    meals, shuttle/return cards, user pins -- act as immovable barriers
    the pass must not overlap; inter-card gaps use the audit formula
    max(30, taxi(km)). Placement/order/durations never change.
    """
    from datetime import time as _time

    from ..inputs.hours_caps import parse_first_window
    from ..inputs.travel import haversine_km

    def _taxi_gap(a_item, b_item):
        la, lb = a_item.location, b_item.location
        if la is None or lb is None:
            return 30
        km = haversine_km(la.lon, la.lat, lb.lon, lb.lat)
        ride = min(180, round(km * 1.3 / 35.0 * 60))
        return max(30, ride + 30)

    def _m(item):
        return item.start_time.hour * 60 + item.start_time.minute

    def _set(item, target, dur):
        end = target + dur
        item.start_time = _time(target // 60 % 24, target % 60)
        item.end_time = _time(end // 60 % 24, end % 60)

    cand_by_poi = {c.poi_id: c for c in snapshot.candidates if c.poi_id}
    for day in plan.days:
        timed = [i for i in day.items if i.start_time is not None]
        fixed = [
            i
            for i in timed
            if getattr(i, "synthetic", False)
            or (i.category or "") in ("transfer", "transport", "food")
            or getattr(i, "access_mode", None)
            or getattr(i, "pinned", False)
        ]
        movable = [
            i for i in timed if i not in fixed and not getattr(i, "pinned", False)
        ]
        if not movable:
            continue
        barriers = sorted(
            [(_m(f), _m(f) + int(f.duration_minutes or 60), f) for f in fixed]
        )

        def _earliest(card, after_min, prev_card):
            cand = cand_by_poi.get(card.poi_id)
            window = parse_first_window(cand.opening_hours if cand else None)
            lo = window[0] if window else after_min
            target = max(lo, after_min)
            dur = int(card.duration_minutes or 60)
            # nudge right past any overlapping barrier
            for _ in range(len(barriers) + 1):
                clash = next(
                    (b for b in barriers if target < b[1] and target + dur > b[0]),
                    None,
                )
                if clash is None:
                    return target
                target = clash[1] + (30 if (card.category or "") != "food" else 0)
            return target

        prev = None
        prev_end = 8 * 60 + 30
        for card in sorted(timed, key=_m):
            if card in movable:
                gap = _taxi_gap(prev, card) if prev is not None else 0
                target = _earliest(card, prev_end + gap if prev else prev_end, prev)
                if target < _m(card):
                    _set(card, target, int(card.duration_minutes or 60))
            prev = card
            prev_end = max(prev_end, _m(card) + int(card.duration_minutes or 60))
    return plan


def materialize_plan(
    solution: "Solution",
    snapshot: "FactSnapshot",
    *,
    itinerary_id: Optional[str] = None,
) -> ItineraryPlan:
    """Base cards + access fields + return cards + unplaced (F-30)."""
    cand_by_cid = {c.cid: c for c in snapshot.candidates}
    legs_by_cid_day = {
        (leg.get("cid"), leg.get("day")): leg for leg in solution.access_legs
    }
    days = []
    seq = 0

    def next_id() -> str:
        nonlocal seq
        seq += 1
        return "v%d" % seq

    for day_no in range(1, snapshot.request.days + 1):
        items: list[VisitItem] = []
        day_items = [it for it in solution.items if it.day == day_no]
        day_items.sort(key=lambda it: (it.start_min, it.cid))
        for sol_item in day_items:
            cand = cand_by_cid.get(sol_item.cid)
            if cand is None:
                continue
            leg = legs_by_cid_day.get((sol_item.cid, day_no))
            card = VisitItem(
                item_id=next_id(),
                name=cand.name,
                poi_id=cand.poi_id,
                category=cand.category,
                city=cand.city or _base_city(snapshot, day_no),
                location=_location(cand),
                opening_hours=cand.opening_hours,
                day=day_no,
                start_time=_hhmm(sol_item.start_min),
                end_time=_hhmm(sol_item.end_min),
                duration_minutes=sol_item.end_min - sol_item.start_min,
                pinned=bool(sol_item.pinned),  # F-20/F-51: 铁律 19 豁免面
                synthetic=False,
                # R6: 打分器/审计的大点豁免与免检口径需要与模型同源——
                # tier 与 best_visit_time 必须随卡（此前只给了 unplaced 行）
                tier=getattr(cand, "tier", None),
                best_visit_time=getattr(cand, "best_visit_time", None),
            )
            if leg is not None:
                # card == leg: the same F-14 interval the model constrained.
                profile = next(
                    (
                        p
                        for p in snapshot.access_profiles
                        if p.to_poi in (cand.poi_id, cand.cid)
                    ),
                    None,
                )
                if profile is not None:  # F-30 fare/service attach
                    card.access_fare_text = profile.fare_text
                    card.access_service_name = profile.operator
                card.access_mode = "access"
                card.access_service_minutes = leg.get("arrive_poi_min", 0) - leg.get(
                    "depart_min", 0
                )
                card.return_hint = RETURN_HINT["zh"]
            items.append(card)
            if leg is not None and leg.get("return_depart_min") is not None:
                arrive_city = leg.get("arrive_city_min")
                ret = VisitItem(
                    item_id="%s%s" % (RETURN_CARD_PREFIX, card.item_id),
                    name="回城",
                    name_en="Return to city",
                    category="transfer",
                    city=_base_city(snapshot, day_no),
                    day=day_no,
                    start_time=_hhmm(int(leg["return_depart_min"])),
                    end_time=(
                        _hhmm(int(arrive_city)) if arrive_city is not None else None
                    ),
                    duration_minutes=(
                        int(arrive_city) - int(leg["return_depart_min"])
                        if arrive_city is not None
                        else None
                    ),
                    synthetic=True,
                )
                items.append(ret)
        days.append(
            DayPlan(day=day_no, base_city=_base_city(snapshot, day_no), items=items)
        )

    cand_by_rid: dict[str, object] = {}
    for cand in snapshot.candidates:
        if cand.rid and cand.rid not in cand_by_rid:
            cand_by_rid[cand.rid] = cand
    unplaced_rows = []
    for entry in solution.unplaced:
        cand = cand_by_rid.get(str(entry.get("rid") or ""))
        unplaced_rows.append(
            UnplacedCandidate(
                name=str(entry.get("name") or ""),
                poi_id=getattr(cand, "poi_id", None),
                category=getattr(cand, "category", None),
                tier=getattr(cand, "tier", None),
                duration_minutes=getattr(cand, "suggested_duration_min", None),
                reason=str(entry.get("reason") or ""),
            )
        )
    must_rids = {m.rid: m.name for m in snapshot.request.musts}
    unplaced_rids = {str(entry.get("rid") or "") for entry in solution.unplaced}
    unarranged = [name for rid, name in must_rids.items() if rid in unplaced_rids]

    plan = ItineraryPlan(
        itinerary_id=itinerary_id or ("it-%s" % snapshot_hash(snapshot)[:12]),
        cities=list(snapshot.request.cities),
        days=days,
        unplaced=unplaced_rows,
        unarranged_musts=unarranged,
        start_date=snapshot.request.start_date,
    )
    ensure_unique_item_ids(plan)
    return plan


def assemble(
    solution: "Solution",
    snapshot: "FactSnapshot",
    *,
    lang: str = "zh",
    itinerary_id: Optional[str] = None,
) -> ItineraryPlan:
    """F-30 -> F-31 -> F-32 -> F-33 in order (annotate_legs materialises
    display legs + fares); F-34 projections are derived separately in
    sync.py; F-33 lines also ride on the solution via
    render_disclosures so both langs stay derivable."""
    from .chips import attach_alternatives
    from .disclosures import render_disclosures
    from .meals import attach_meal_cards

    plan = materialize_plan(solution, snapshot, itinerary_id=itinerary_id)
    plan = attach_meal_cards(plan, solution, snapshot)
    plan = compact_days(plan, snapshot)
    plan = attach_alternatives(plan, snapshot)
    from ...itinerary.legs import annotate_legs

    plan = annotate_legs(plan)  # F-30 display legs + fare materialisation
    plan.assumptions = render_disclosures(solution, snapshot, lang=lang)
    return plan
