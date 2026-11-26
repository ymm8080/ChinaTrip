"""F-34 session/trip-center sync inputs (engine-independent).

The session writes themselves stay with the legacy agent-level sync
(``sync_trip_rows`` / ``_sync_wish_rows`` / ``_sync_planned_rows`` /
``sync_removals_to_trip_items``) — behavior unchanged, invoked at the
P3 serving seam. This module derives the machine rows those syncs
consume from F-30's materialised plan, plus the shared item-id
self-healing (pure, reused verbatim).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...itinerary.item_ids import ensure_unique_item_ids
from ...itinerary.models import VisitItem

if TYPE_CHECKING:  # pragma: no cover
    from ...itinerary.models import ItineraryPlan


def finalize_plan(plan: "ItineraryPlan") -> list[str]:
    """Item-id self-healing (legacy Day6 422 incident guard)."""
    return ensure_unique_item_ids(plan)


def wish_row_projection(plan: "ItineraryPlan") -> list[dict]:
    """Rows the wish-list sync consumes: unplaced candidates with the
    F-26 reason attached."""
    return [
        {
            "name": u.name,
            "poi_id": u.poi_id,
            "day_hint": u.day_hint,
            "reason": u.reason,
        }
        for u in plan.unplaced
    ]


def planned_row_projection(plan: "ItineraryPlan") -> list[dict]:
    """Rows the planned-rows sync consumes: one per scheduled card."""
    return [
        {
            "item_id": it.item_id,
            "day": d.day,
            "name": it.name,
            "poi_id": it.poi_id,
        }
        for d in plan.days
        for it in d.items
        if isinstance(it, VisitItem) and not it.synthetic
    ]
