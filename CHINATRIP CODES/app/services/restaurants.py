"""Restaurant recommendation tool (design §6.2 v1.7 + §6.4 iron rule 20).

recommend_restaurants(day_plan, meal_slot): lunch/dinner free-window x
detour (on-the-way) x amap rating x walking distance, returned as food
VisitItems reusing pois.category=food — zero new tables.

Iron rule 20 division of labor (§6.4: 只落用餐时段空窗、复用营业时间与
顺路校验、不得挤占核心游览或移动用户已确认条目):

- THIS module owns the tool-side half: candidates are produced only when
  the meal slot still has a free gap inside the meal window (no gap -> []),
  and every food item is built unpinned (pinned=False) so it can never
  displace user-confirmed entries (rule 19) nor move core sightseeing.
- The CALLER (orchestrator) inserts items through the unified mutation
  pipeline (apply_diffs); final non-overlap (rule 1) and restaurant
  opening hours (rule 2, poi_hours) are enforced by validate_plan there.

Degradation contract: a missing or raising amap client yields [] — an
empty recommendation never breaks the main planning flow.
"""

import logging
import math
from datetime import time
from typing import Literal, Protocol

from pydantic import BaseModel

from app.services.itinerary.models import DayPlan, GeoPoint, VisitItem

logger = logging.getLogger(__name__)

MealSlot = Literal["lunch", "dinner"]

# Meal window constants (local time of the itinerary city, iron rule 13).
MEAL_WINDOWS: dict[MealSlot, tuple[time, time]] = {
    "lunch": (time(11, 30), time(13, 30)),
    "dinner": (time(17, 30), time(19, 30)),
}

MEAL_DURATION_MINUTES = 60  # a meal occupies one hour of the free gap
TOP_N_RECOMMENDATIONS = 3
WALK_METERS_PER_MINUTE = 80.0  # ~4.8 km/h pedestrian estimate
RATING_WEIGHT = 0.1  # rating * weight is subtracted from detour score
# Fixed tail rank for candidates we cannot geo-locate (and for the
# degenerate no-route-points case, where on-the-way-ness is undefined).
NO_LOCATION_DETOUR_SCORE = 999.0

_RESTAURANT_KEYWORD = "餐厅"

_EARTH_RADIUS_M = 6371000.0


class AmapSearchService(Protocol):
    """Duck-typed slice of AmapClient used here (injected, stub-friendly)."""

    async def search_poi(
        self, keywords: str, *, city: str | None = None, page: int = 1
    ) -> list[dict]: ...


class RestaurantCandidate(BaseModel):
    """One restaurant hit from amap, enriched during ranking."""

    name: str
    poi_id: str | None = None
    location: GeoPoint | None = None
    address: str | None = None
    opening_hours: str | None = None
    walk_minutes: int | None = None  # to the search anchor, if provided
    detour_score: float = 0.0  # km to nearest route point; smaller = better
    rating: float | None = None  # amap extension field, often missing
    biz_type: str | None = None


def _haversine_m(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle distance in meters (self-contained, no deps)."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2.0 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _time_of(total_minutes: int) -> time:
    return time(total_minutes // 60, total_minutes % 60)


def _as_float(value: object) -> float | None:
    """Tolerant numeric coercion (amap may return strings or omit fields)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def search_restaurants(
    amap_client: AmapSearchService | None,
    city: str,
    *,
    anchor: GeoPoint | None = None,
    limit: int = 10,
) -> list[RestaurantCandidate]:
    """Search restaurants in `city` via the amap "餐厅" keyword.

    Degradation contract (§6.2): no client, a non-positive limit or any
    amap failure -> [] — the caller keeps planning without restaurants.
    `rating` is an amap extension field and may be absent -> None.
    With an `anchor`, walk_minutes is the straight-line walking time to it.
    """
    if amap_client is None or limit <= 0:
        return []
    try:
        pois = await amap_client.search_poi(_RESTAURANT_KEYWORD, city=city)
    except Exception:
        logger.warning(
            "restaurants: search failed for %s, returning []", city, exc_info=True
        )
        return []  # degraded empty recommendation, never raise upstream
    candidates: list[RestaurantCandidate] = []
    for poi in pois[:limit]:
        name = poi.get("name")
        if not name:
            continue
        raw_loc = poi.get("location")
        location = None
        if isinstance(raw_loc, dict):
            lon = _as_float(raw_loc.get("lon"))
            lat = _as_float(raw_loc.get("lat"))
            if lon is not None and lat is not None:
                location = GeoPoint(lon=lon, lat=lat)
        walk_minutes = None
        if anchor is not None and location is not None:
            meters = _haversine_m(anchor, location)
            walk_minutes = round(meters / WALK_METERS_PER_MINUTE)
        candidates.append(
            RestaurantCandidate(
                name=name,
                poi_id=poi.get("source_poi_id"),
                location=location,
                address=poi.get("address"),
                opening_hours=poi.get("opening_hours"),
                walk_minutes=walk_minutes,
                rating=_as_float(poi.get("rating")),
                biz_type=poi.get("category"),
            )
        )
    return candidates


def meal_window(day: DayPlan, slot: MealSlot) -> tuple[time, time] | None:
    """Free gap of the meal window on that day (iron rule 20).

    Window constant minus the time coverage of existing items (end_time,
    or start+duration when end is missing; untimed items do not block).
    Untimed day -> the window constant as-is. Of the remaining gaps the
    largest one that still fits MEAL_DURATION_MINUTES wins (ties ->
    earliest); fully occupied (or no gap fits a meal) -> None — no free
    gap means no forced insertion.
    """
    win_start, win_end = MEAL_WINDOWS[slot]
    ws, we = _minutes(win_start), _minutes(win_end)
    blocked: list[tuple[int, int]] = []
    for item in day.items:
        if item.start_time is None:
            continue
        end = _minutes(item.end_time) if item.end_time is not None else None
        if end is None and item.duration_minutes is not None:
            end = _minutes(item.start_time) + item.duration_minutes
        if end is None:
            continue
        start = max(_minutes(item.start_time), ws)
        end = min(end, we)
        if start < end:  # clipped overlap with the meal window
            blocked.append((start, end))
    if not blocked:
        return (win_start, win_end)
    blocked.sort()
    gaps: list[tuple[int, int]] = []
    cursor = ws
    for start, end in blocked:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < we:
        gaps.append((cursor, we))
    gaps = [(s, e) for s, e in gaps if e - s >= MEAL_DURATION_MINUTES]
    if not gaps:
        return None
    best = max(gaps, key=lambda g: (g[1] - g[0], -g[0]))
    return (_time_of(best[0]), _time_of(best[1]))


def rank_by_detour(
    candidates: list[RestaurantCandidate],
    *,
    route_points: list[GeoPoint],
) -> list[RestaurantCandidate]:
    """Sort candidates by on-the-way-ness (smaller final score first).

    detour_score = km from the candidate to its nearest route point
    (min haversine over all points). Unlocatable candidates — and the
    degenerate no-route-points case — get the fixed tail score
    NO_LOCATION_DETOUR_SCORE. Final score = detour_score - rating *
    RATING_WEIGHT when a rating exists, so better-rated places win ties
    and near-ties. Candidates' detour_score is populated in place.
    """
    for cand in candidates:
        if cand.location is None or not route_points:
            cand.detour_score = NO_LOCATION_DETOUR_SCORE
        else:
            meters = min(_haversine_m(cand.location, p) for p in route_points)
            cand.detour_score = meters / 1000.0

    def final_score(cand: RestaurantCandidate) -> float:
        bonus = cand.rating * RATING_WEIGHT if cand.rating is not None else 0.0
        return cand.detour_score - bonus

    return sorted(candidates, key=final_score)


def build_food_item(
    candidate: RestaurantCandidate,
    *,
    day: int,
    city: str,
    window: tuple[time, time],
    item_id: str,
) -> VisitItem:
    """Convert a ranked candidate into an addable food VisitItem.

    start_time = midpoint of the free-gap window, one-hour duration,
    unpinned (iron rule 20: never displaces user-confirmed items, rule 19
    stays intact). Final non-overlap is guaranteed by validate_plan in
    the caller's mutation pipeline, not here.
    """
    mid = (_minutes(window[0]) + _minutes(window[1])) // 2
    return VisitItem(
        item_id=item_id,
        name=candidate.name,
        poi_id=candidate.poi_id,
        category="food",
        city=city,
        location=candidate.location,
        address=candidate.address,
        opening_hours=candidate.opening_hours,
        day=day,
        start_time=_time_of(mid),
        end_time=_time_of(mid + MEAL_DURATION_MINUTES),
        duration_minutes=MEAL_DURATION_MINUTES,
        pinned=False,
    )


async def recommend_restaurants(
    amap_client: AmapSearchService | None,
    day_plan: DayPlan,
    slot: MealSlot,
    *,
    city: str | None = None,
) -> list[VisitItem]:
    """Top-N ready-to-add food items for the meal slot (§6.2 v1.7).

    Pipeline: meal_window (no free gap -> [], iron rule 20: never force a
    meal into an occupied slot) -> search_restaurants (amap failure -> [])
    -> rank_by_detour (route = that day's located VisitItems) ->
    build_food_item (unpinned, inside the gap). The caller inserts the
    returned items via apply_diffs and relies on validate_plan for rules
    1/2 (non-overlap, poi_hours) — see module docstring for the split.
    """
    window = meal_window(day_plan, slot)
    if window is None:
        return []
    city_used = city or day_plan.base_city
    candidates = await search_restaurants(amap_client, city_used)
    # 当天已排的 POI 不再当餐厅推荐（同站景点不是用餐点；2026-10-31
    # 外滩案：松散候选源把已排景点又排成晚餐，造成同天双卡）
    planned_pids = {
        i.poi_id for i in day_plan.items if isinstance(i, VisitItem) and i.poi_id
    }
    candidates = [c for c in candidates if c.poi_id not in planned_pids]
    route_points = [
        item.location
        for item in day_plan.items
        if isinstance(item, VisitItem) and item.location is not None
    ]
    ranked = rank_by_detour(candidates, route_points=route_points)
    return [
        build_food_item(
            cand,
            day=day_plan.day,
            city=city_used,
            window=window,
            item_id=f"food-d{day_plan.day}-{slot}-{index + 1}",
        )
        for index, cand in enumerate(ranked[:TOP_N_RECOMMENDATIONS])
    ]
