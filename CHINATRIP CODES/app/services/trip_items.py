"""Trip-center three-state items (design v2.4 §5/§4).

One table absorbs every write path — manual form, chat dialog, paste box,
agent recommendation (iron rule 0: single source of truth). An item walks
Wishlist -> Scheduled -> Booked; walking back to wishlist unschedules it.
Pure logic only (store + transition rules): no HTTP imports, so the state
machine is unit-testable directly. Storage is a plain dict;
``state_persist.PersistentTripItemService`` subclasses it with SQLite
write-through so items survive restarts (itinerary-store pattern).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

STATUS_WISHLIST = "wishlist"
STATUS_SCHEDULED = "scheduled"
STATUS_BOOKED = "booked"
STATUS_UNWANTED = "unwanted"
STATUSES = frozenset(
    {STATUS_WISHLIST, STATUS_SCHEDULED, STATUS_BOOKED, STATUS_UNWANTED}
)

SOURCES = frozenset({"manual", "chat", "paste", "agent_recommend", "plan_delete"})

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


def _norm(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().casefold() or None


# 2026-10-28 心愿单去重模糊层：同一意愿的不同写法（看变脸 /
# 变脸表演（川剧）/ 川剧变脸）必须收成一张卡。键 = 剥括号注 + 意图动词
# 前缀 + 通用活动后缀；匹配 = 键相等 或 双向包含（短侧 >= 2 字，POIS
# 数据集同款包含规则）。
_WISH_PAREN_RE = re.compile(r"[（(【\[][^\n（）()【\][]*[）)】\]]")
_WISH_VERB_PREFIX = (
    "想要",
    "想看",
    "想去",
    "想逛",
    "想吃",
    "想喝",
    "想玩",
    "想体验",
    "看看",
    "逛逛",
    "试试",
    "尝尝",
    "参观",
    "游览",
    "打卡",
    "体验",
    "品尝",
    "看",
    "去",
    "吃",
    "喝",
    "逛",
    "游",
    "玩",
)
_WISH_GENERIC_SUFFIX = ("表演", "演出", "体验", "秀", "之旅")


def _wish_key(value: str | None) -> str:
    name = _norm(value)
    if not name:
        return ""
    name = _WISH_PAREN_RE.sub("", name)
    name = re.sub(r"\s+", "", name)
    for _ in range(3):  # 前缀/后缀交替剥，三轮收敛（看看变脸表演→变脸）
        changed = False
        for prefix in _WISH_VERB_PREFIX:
            if name.startswith(prefix) and len(name) > len(prefix):
                name = name[len(prefix) :]
                changed = True
        for suffix in _WISH_GENERIC_SUFFIX:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
                changed = True
        if not changed:
            break
    return name


def _wish_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    short, other = (left, right) if len(left) <= len(right) else (right, left)
    return len(short) >= 2 and short in other


class TripItemService:
    """In-memory trip-item store + Wishlist/Scheduled/Booked state machine.

    Invariants enforced after every update:
      * wishlist  -> day/position/booking_id are None
      * scheduled -> day/position set, booking_id None
      * booked    -> day/position/booking_id set
      * unwanted  -> day/position/booking_id are None
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
        """Idempotent create: returns the existing row instead of a new one
        when this trip already holds the same poi_id / name+city (an empty
        city matches any). 2026-10-28 user report (multiple 西湖 on the
        global board): a same-name wishlist row from another trip is the
        same wish too — see _find_duplicate for the exact predicate."""
        if source not in SOURCES:
            raise InvalidSourceError(f"invalid_source:{source}")
        duplicate = self._find_duplicate(
            name,
            source=source,
            itinerary_id=itinerary_id,
            city=city,
            poi_id=poi_id,
        )
        if duplicate is not None:
            # Same wish, richer info: fill ONLY empty fields of the existing
            # row (a deliberate 杭州 never becomes 苏州); the row survives
            # with everything the second submission knew.
            self._enrich_duplicate(
                duplicate,
                name=name,
                note=note,
                city=city,
                poi_id=poi_id,
                address=address,
                opening_hours=opening_hours,
                now=now,
            )
            logger.info(
                "trip_item_deduplicated id=%s name=%s",
                duplicate["id"],
                duplicate["name"],
            )
            return dict(duplicate)
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

    @staticmethod
    def _enrich_duplicate(
        item: dict,
        *,
        name: str | None = None,
        note: str | None,
        city: str | None,
        poi_id: str | None,
        address: str | None,
        opening_hours: str | None,
        now: datetime | None,
    ) -> None:
        """Merge-in place: only fill fields the existing row lacks; record
        a rephrased alias (看变脸 vs 变脸表演（川剧）) in note so a fuzzy
        merge leaves visible trace; bump updated_at when anything changed
        (subclass persistence rides the caller's write-through)."""
        changed = False
        for field, value in (
            ("note", note),
            ("city", city),
            ("poi_id", poi_id),
            ("address", address),
            ("opening_hours", opening_hours),
        ):
            if value and not item.get(field):
                item[field] = value
                changed = True
        alias = (name or "").strip()
        if alias and _norm(alias) != _norm(item.get("name")):
            current = item.get("note") or ""
            if alias not in current:
                merged = f"{current}；别名：{alias}" if current else f"别名：{alias}"
                item["note"] = merged
                changed = True
        if changed:
            item["updated_at"] = _iso_now(now)

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
            "unwanted": sorted(
                (dict(i) for i in items if i["status"] == STATUS_UNWANTED),
                key=lambda i: i["updated_at"],
                reverse=True,
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
        if target in (STATUS_WISHLIST, STATUS_UNWANTED):
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

    def mark_unwanted(
        self,
        name: str,
        *,
        itinerary_id: str | None = None,
        city: str | None = None,
    ) -> dict:
        """Plan-delete path: park the item in the unwanted group (or file a
        fresh unwanted entry when the plan never had one)."""
        for item in self._items.values():
            if item["itinerary_id"] == itinerary_id and item["name"] == name:
                if item["status"] != STATUS_UNWANTED:
                    return self.update(item["id"], status=STATUS_UNWANTED)
                return dict(item)
        created = self.create(
            name, source="plan_delete", itinerary_id=itinerary_id, city=city
        )
        return self.update(created["id"], status=STATUS_UNWANTED)

    # --- rules ----------------------------------------------------------------

    @staticmethod
    def _check_transition(
        current: str, target: str, *, day: int | None, booking_id: str | None
    ) -> None:
        """Legal edges of the state machine (everything else 422):
        wishlist->scheduled (day required), scheduled->booked (booking_id
        required), scheduled/booked->wishlist (un-schedule clears fields),
        wishlist/scheduled/booked->unwanted, unwanted->wishlist (restore).
        """
        if current == STATUS_WISHLIST and target == STATUS_SCHEDULED:
            if day is None or day < 1:
                raise InvalidTransitionError(f"day_required:{day}")
        elif current == STATUS_SCHEDULED and target == STATUS_BOOKED:
            if booking_id is None or not booking_id.strip():
                raise InvalidTransitionError("booking_id_required")
        elif target == STATUS_WISHLIST and current in _TIMELINE_STATUSES:
            pass
        elif target == STATUS_UNWANTED and current != STATUS_UNWANTED:
            pass
        elif current == STATUS_UNWANTED and target == STATUS_WISHLIST:
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

    def _find_duplicate(
        self,
        name: str,
        *,
        source: str,
        itinerary_id: str | None,
        city: str | None,
        poi_id: str | None,
        items: Iterable[dict] | None = None,
    ) -> dict | None:
        """Same trip + same thing = one row: poi_id is authoritative when
        both sides carry it, else the wish key (see _wish_key) matched by
        equality or bidirectional containment + city compatibility — a
        missing city never contradicts a known one (chat adds a bare 西湖,
        paste adds 西湖+杭州: same wish). Unwanted rows never match —
        re-adding a rejected item starts a fresh wishlist entry.
        2026-10-28 user report (the global board showed 西湖 once per
        trip): a same-name WISHLIST row from another trip is the same wish
        too. Same-day follow-up (变脸 twice on the board): 看变脸 /
        变脸表演（川剧）/ 川剧变脸 are one wish phrased three ways — hence
        the normalized key + containment layer instead of raw equality.
        Scheduled/booked rows of other trips never match (a new trip files
        its own wish — timeline rows stay per-trip), and the plan_delete
        bookkeeping write never global-merges (un-parking trip B must not
        flip trip A's wish). PgTripItemService feeds advisory-locked DB
        rows straight into this predicate — single implementation, no SQL
        mirror."""
        active = self._items.values() if items is None else items
        if poi_id:
            for item in active:
                if (
                    item["itinerary_id"] == itinerary_id
                    and item["status"] != STATUS_UNWANTED
                    and item["poi_id"] == poi_id
                ):
                    return item
        key_name, key_city = _norm(name), _norm(city)
        wish_key = _wish_key(name)
        for item in active:
            if item["status"] == STATUS_UNWANTED:
                continue
            if not (
                _norm(item["name"]) == key_name
                or _wish_match(wish_key, _wish_key(item["name"]))
            ):
                continue
            item_city = _norm(item["city"])
            if key_city is not None and item_city is not None and item_city != key_city:
                continue
            if item["itinerary_id"] == itinerary_id:
                return item
            if source != "plan_delete" and item["status"] == STATUS_WISHLIST:
                return item
        return None
