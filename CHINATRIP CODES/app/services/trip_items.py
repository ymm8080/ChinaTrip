"""Trip-center three-state items (design v2.4 §5/§4).

One table absorbs every write path — manual form, chat dialog, paste box,
agent recommendation (iron rule 0: single source of truth). An item walks
Wishlist -> Scheduled -> Booked; walking back to wishlist unschedules it.
Pure logic only (store + transition rules): no HTTP imports, so the state
machine is unit-testable directly. Storage is an in-process dict — process
restart wipes it (MVP consensus, same as the itinerary store).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

STATUS_WISHLIST = "wishlist"
STATUS_SCHEDULED = "scheduled"
STATUS_BOOKED = "booked"
STATUSES = frozenset({STATUS_WISHLIST, STATUS_SCHEDULED, STATUS_BOOKED})

SOURCES = frozenset({"manual", "chat", "paste", "agent_recommend"})

# Statuses that occupy a (day, position) slot on the timeline.
_TIMELINE_STATUSES = frozenset({STATUS_SCHEDULED, STATUS_BOOKED})


class InvalidSourceError(ValueError):
    """Create payload named a source outside the four allowed origins."""


class NotFoundError(KeyError):
    """No item with that id."""


class InvalidTransitionError(ValueError):
    """Requested change violates the three-state machine."""


def _iso_now(now: datetime | None) -> str:
    return (now if now is not None else datetime.now(timezone.utc)).isoformat()


class TripItemService:
    """In-memory trip-item store + Wishlist/Scheduled/Booked state machine.

    Invariants enforced after every update:
      * wishlist  -> day/position/booking_id are None
      * scheduled -> day/position set, booking_id None
      * booked    -> day/position/booking_id set
    day/position/booking_id are owned by the state machine: values supplied
    for them while the item ends up in wishlist are discarded.
    """

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    # --- create / read -------------------------------------------------------

    def create(
        self,
        name: str,
        *,
        source: str,
        itinerary_id: str | None = None,
        city: str | None = None,
        note: str | None = None,
        poi_id: str | None = None,
        address: str | None = None,
        opening_hours: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        if source not in SOURCES:
            raise InvalidSourceError(f"invalid_source:{source}")
        stamp = _iso_now(now)
        item = {
            "id": uuid4().hex,
            "itinerary_id": itinerary_id,
            "name": name,
            "city": city,
            "note": note,
            "status": STATUS_WISHLIST,
            "source": source,
            "poi_id": poi_id,
            "address": address,
            "opening_hours": opening_hours,
            "day": None,
            "position": None,
            "booking_id": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        self._items[item["id"]] = item
        logger.info("trip_item_created source=%s", source)
        return dict(item)

    def get(self, item_id: str) -> dict | None:
        item = self._items.get(item_id)
        return dict(item) if item is not None else None

    def list_groups(self, itinerary_id: str | None = None) -> dict:
        """Timeline payload (§5): Bookings pinned first, Wishlist stream,
        Scheduled as the third key — each in its documented order."""
        items = list(self._items.values())
        if itinerary_id is not None:
            items = [i for i in items if i["itinerary_id"] == itinerary_id]

        def timeline_key(item: dict) -> tuple[int, float]:
            return (item["day"], item["position"])

        return {
            "bookings": sorted(
                (dict(i) for i in items if i["status"] == STATUS_BOOKED),
                key=timeline_key,
            ),
            "wishlist": sorted(
                (dict(i) for i in items if i["status"] == STATUS_WISHLIST),
                key=lambda i: i["created_at"],
                reverse=True,
            ),
            "scheduled": sorted(
                (dict(i) for i in items if i["status"] == STATUS_SCHEDULED),
                key=timeline_key,
            ),
        }

    # --- update / delete -----------------------------------------------------

    def update(
        self,
        item_id: str,
        *,
        status: str | None = None,
        day: int | None = None,
        position: float | None = None,
        note: str | None = None,
        city: str | None = None,
        booking_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        item = self._items.get(item_id)
        if item is None:
            raise NotFoundError(item_id)
        if status is not None and status not in STATUSES:
            raise InvalidTransitionError(f"unknown_status:{status}")

        current = item["status"]
        target = status if status is not None else current

        if status is not None and status != current:
            self._check_transition(current, target, day=day, booking_id=booking_id)
            if current == STATUS_WISHLIST and target == STATUS_SCHEDULED:
                if position is None:
                    position = self._next_position(item["itinerary_id"], day)
        else:
            # Same-status patch: a day move without explicit position lands
            # at the end of the new day.
            self._check_fields(target, day=day, booking_id=booking_id)
            if (
                target in _TIMELINE_STATUSES
                and day is not None
                and position is None
                and day != item["day"]
            ):
                position = self._next_position(item["itinerary_id"], day)

        item["status"] = target
        if target == STATUS_WISHLIST:
            item["day"] = None
            item["position"] = None
            item["booking_id"] = None
        else:
            if day is not None:
                item["day"] = day
            if position is not None:
                item["position"] = float(position)
            if booking_id is not None:
                item["booking_id"] = booking_id
            if target == STATUS_SCHEDULED:
                item["booking_id"] = None
        if note is not None:
            item["note"] = note
        if city is not None:
            item["city"] = city
        item["updated_at"] = _iso_now(now)
        return dict(item)

    def delete(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if item is None:
            raise NotFoundError(item_id)
        if item["status"] == STATUS_BOOKED:
            # §5 timeline integrity: un-book before removing.
            raise InvalidTransitionError("booked_not_deletable")
        del self._items[item_id]
        logger.info("trip_item_deleted id=%s", item_id)

    # --- rules ----------------------------------------------------------------

    @staticmethod
    def _check_transition(
        current: str, target: str, *, day: int | None, booking_id: str | None
    ) -> None:
        """Legal edges of the three-state machine (everything else 422):
        wishlist->scheduled (day required), scheduled->booked (booking_id
        required), scheduled/booked->wishlist (un-schedule clears fields).
        """
        if current == STATUS_WISHLIST and target == STATUS_SCHEDULED:
            if day is None or day < 1:
                raise InvalidTransitionError(f"day_required:{day}")
        elif current == STATUS_SCHEDULED and target == STATUS_BOOKED:
            if booking_id is None or not booking_id.strip():
                raise InvalidTransitionError("booking_id_required")
        elif target == STATUS_WISHLIST and current in _TIMELINE_STATUSES:
            pass
        else:
            raise InvalidTransitionError(f"{current}_to_{target}")

    @staticmethod
    def _check_fields(target: str, *, day: int | None, booking_id: str | None) -> None:
        if day is not None and day < 1:
            raise InvalidTransitionError(f"day_invalid:{day}")
        if booking_id is not None and not booking_id.strip():
            raise InvalidTransitionError("booking_id_required")

    def _next_position(self, itinerary_id: str | None, day: int) -> float:
        """Append after the last timeline item of the same trip/day."""
        positions = [
            item["position"]
            for item in self._items.values()
            if item["itinerary_id"] == itinerary_id
            and item["day"] == day
            and item["status"] in _TIMELINE_STATUSES
            and item["position"] is not None
        ]
        return max(positions) + 1.0 if positions else 1.0
