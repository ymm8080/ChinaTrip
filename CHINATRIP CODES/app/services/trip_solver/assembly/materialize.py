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
                synthetic=False,
            )
            if leg is not None:
                # card == leg: the same F-14 interval the model constrained.
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
    """F-30 -> F-31 -> F-32 -> F-33 in order; F-34 projections are
    solution (render_disclosures) so both langs stay derivable."""
    from .chips import attach_alternatives
    from .disclosures import render_disclosures
    from .meals import attach_meal_cards

    plan = materialize_plan(solution, snapshot, itinerary_id=itinerary_id)
    plan = attach_meal_cards(plan, solution, snapshot)
    plan = attach_alternatives(plan, snapshot)
    plan.assumptions = render_disclosures(solution, lang=lang)
    return plan
