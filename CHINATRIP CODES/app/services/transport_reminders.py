"""Departure reminders + missed-connection fallback for train/flight legs
(design v2.2 §6.13: 火车/飞机 = 行程层管理，非导航).

Trains/flights are itinerary-layer objects: the static timetable (12306 /
flight schedule) lands on the timeline as cross-city cards, we push
leave-for-the-station reminders before departure, and when the user misses
the leg we hand them a free recovery card (nearest departures + taxi
deeplink). In-station/airport navigation is explicitly out of scope.

Buffer semantics: :data:`TRAIN_LEAVE_BUFFER_MINUTES` /
:data:`FLIGHT_LEAVE_BUFFER_MINUTES` are "leave for the station/airport now"
lead times (赶到车站/机场的出发缓冲). They are a different quantity from
``INTERCITY_BUFFER_MINUTES = 90`` in :mod:`app.services.itinerary.models`
(iron rule 4: buffer between two items in a plan, 行程衔接缓冲) — 赶车提前量
≠ 行程衔接缓冲 — so each keeps its own value: train 45, flight 90 (the
flight 90 numerically coincides with the connection buffer but is defined
independently).

All datetimes are naive local time in the trip city's timezone; converting
from wall-clock/UTC is the client's job (same convention as §6.13).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from app.services.trains import TrainService

TRAIN_LEAVE_BUFFER_MINUTES = 45  # lead time to get to the railway station
FLIGHT_LEAVE_BUFFER_MINUTES = 90  # lead time to get to the airport

_LEAVE_BUFFER_MINUTES: dict[str, int] = {
    "train": TRAIN_LEAVE_BUFFER_MINUTES,
    "flight": FLIGHT_LEAVE_BUFFER_MINUTES,
}

MAX_NEXT_DEPARTURES = 3


def build_departure_reminders(leg: dict, *, now: datetime | None = None) -> list[dict]:
    """Three-tier departure reminders for one train/flight leg.

    leg = {"type": "train"|"flight", "departure_time": datetime,
           "station_name": str, "station_location": {"lon", "lat"} | None}

    Tiers (at = departure_time minus offset, naive local time):
      - heads_up  at -24h  "明天从{station_name}出发"
      - prepare   at -2h   "2小时后从{station_name}出发"
      - leave_now at -buffer(TRAIN 45 / FLIGHT 90)

    ``now=None`` means "do not filter" (client filters itself); otherwise
    only tiers with ``at > now`` are returned. Result is sorted by ``at``
    ascending. Raises ValueError on an unknown type or a missing
    departure_time.
    """
    leg_type = leg.get("type")
    if leg_type not in _LEAVE_BUFFER_MINUTES:
        raise ValueError(f"unsupported leg type: {leg_type!r} (train|flight)")
    departure = leg.get("departure_time")
    if not isinstance(departure, datetime):
        raise ValueError("leg['departure_time'] (datetime) is required")

    station_name = leg["station_name"]
    buffer_minutes = _LEAVE_BUFFER_MINUTES[leg_type]
    tiers = (
        (
            "heads_up",
            departure - timedelta(hours=24),
            f"明天从{station_name}出发",
        ),
        (
            "prepare",
            departure - timedelta(hours=2),
            f"2小时后从{station_name}出发",
        ),
        (
            "leave_now",
            departure - timedelta(minutes=buffer_minutes),
            f"现在出发去{station_name}（预留{buffer_minutes}分钟缓冲）",
        ),
    )
    reminders = [
        {"at": at, "kind": kind, "message": message} for kind, at, message in tiers
    ]
    if now is not None:
        reminders = [r for r in reminders if r["at"] > now]
    reminders.sort(key=lambda r: r["at"])
    return reminders


async def missed_connection_fallback(
    leg: dict,
    *,
    train_service: TrainService,
    taxi_deeplink_builder: Callable[[str, float, float], dict | None],
    now: datetime | None = None,
) -> dict:
    """Missed-connection recovery card (§6.13 → §6.7 永远免费).

    This is a benefit-exemption path: it is ALWAYS free — no metered
    deeplink, no quota, no charge, ever. The caller decides that the leg
    was missed (departure_time < now); this function never asserts it.

    leg: same shape as :func:`build_departure_reminders`, plus
    ``from_city``/``to_city`` for train legs (the static timetable's query
    granularity is the city pair — same as TransferItem's from/to city).

    Train: queries ``train_service.search(from_city, to_city, date)`` for
    the leg's travel date and keeps departures with ``dep_time > now``
    (same-day recovery: the static lib carries time-of-day only), sorted
    ascending, at most :data:`MAX_NEXT_DEPARTURES` entries in TrainOption
    shape (pass-through). Flight: no flight static lib exists in MVP, so
    next_departures is always [] — we never fabricate flights; the note
    redirects to rebooking/airline.

    ``taxi_deeplink_builder(station_name, lon, lat)`` is injected by the
    route layer (deeplinks module) — deliberately not imported here. When
    station_location (or station_name) is absent, ``taxi`` is None: a
    deeplink cannot be synthesized without coordinates.
    """
    leg_type = leg.get("type")
    if leg_type not in _LEAVE_BUFFER_MINUTES:
        raise ValueError(f"unsupported leg type: {leg_type!r} (train|flight)")
    departure = leg.get("departure_time")
    if not isinstance(departure, datetime):
        raise ValueError("leg['departure_time'] (datetime) is required")

    station_name = leg.get("station_name")
    location = leg.get("station_location")
    taxi = None
    if station_name and location:
        taxi = taxi_deeplink_builder(station_name, location["lon"], location["lat"])

    if leg_type == "flight":
        return {
            "leg_type": "flight",
            "next_departures": [],
            "taxi": taxi,
            "note": "MVP 无航班静态库，请改签或联系航司；打车前往机场兜底",
        }

    from_city = leg.get("from_city")
    to_city = leg.get("to_city")
    if not from_city or not to_city:
        raise ValueError(
            "train leg requires from_city/to_city "
            "(the static timetable is queried by city pair)"
        )
    options = await train_service.search(
        from_city, to_city, departure.date().isoformat()
    )
    if now is not None:
        options = [o for o in options if o.dep_time > now.time()]
    options = sorted(options, key=lambda o: o.dep_time)[:MAX_NEXT_DEPARTURES]
    return {
        "leg_type": "train",
        "next_departures": [o.model_dump() for o in options],
        "taxi": taxi,
        "note": "误车应急兜底永远免费",
    }
