"""F-32 alternatives chips from the snapshot pool (geometry only).

v1 rule (legacy pick_alternatives adapted to snapshot data): same city,
distance <= 0.3 km straight line, not already in the plan, cap 3 per
card. "want" chips stay on plan.unplaced (the dedicated want surface);
this attaches same-vicinity alternatives on host cards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...itinerary.models import PlanAlternative, VisitItem
from ..inputs.travel import haversine_km

if TYPE_CHECKING:  # pragma: no cover
    from ...itinerary.models import ItineraryPlan
    from ..types import FactSnapshot

CHIP_RADIUS_KM = 0.3
CHIP_CAP = 3


def attach_alternatives(
    plan: "ItineraryPlan",
    snapshot: "FactSnapshot",
    *,
    radius_km: float = CHIP_RADIUS_KM,
) -> "ItineraryPlan":
    seated_pois = {
        i.poi_id for d in plan.days for i in d.items if isinstance(i, VisitItem)
    }
    pool = [
        c
        for c in snapshot.candidates
        if c.lon is not None and c.lat is not None and c.poi_id not in seated_pois
    ]
    for day in plan.days:
        for item in day.items:
            if not isinstance(item, VisitItem) or item.location is None:
                continue
            chips: list[PlanAlternative] = []
            for cand in pool:
                if cand.poi_id == item.poi_id:
                    continue
                if cand.city and item.city and cand.city != item.city:
                    continue
                dist = haversine_km(
                    item.location.lon,
                    item.location.lat,
                    float(cand.lon),
                    float(cand.lat),
                )
                if dist > radius_km:
                    continue
                candidate_chip = PlanAlternative(
                    name=cand.name,
                    category=cand.category,
                    tier=cand.tier,
                    distance_km=round(dist, 2),
                )
                chips.append(candidate_chip)
            if chips:
                item.alternatives = sorted(  # rank by distance, then cap
                    chips, key=lambda a: (a.distance_km or 0.0, a.name)
                )[:CHIP_CAP]
    return plan
