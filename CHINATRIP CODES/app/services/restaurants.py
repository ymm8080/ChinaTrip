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
import re
from datetime import time
from typing import Literal, Protocol

from pydantic import BaseModel

from app.services.best_visit import infer_slot_from_hours
from app.services.itinerary.models import DayPlan, GeoPoint, VisitItem

logger = logging.getLogger(__name__)

MealSlot = Literal["lunch", "dinner"]

# Meal window constants (local time of the itinerary city, iron rule 13).
# 午餐窗 12:00–13:30（2026-10-31 拍板：默认午饭时间，原 11:30–13:30）。
MEAL_WINDOWS: dict[MealSlot, tuple[time, time]] = {
    "lunch": (time(12, 0), time(13, 30)),
    "dinner": (time(17, 30), time(19, 30)),
}

MEAL_DURATION_MINUTES = 60  # a meal occupies one hour of the free gap
# 午餐口径（2026-11-03 拍板）：开餐硬窗 [11:30, 12:30]，时长默认 1.5h、
# 极端可缩 0.5h。晚餐/通用餐仍走 MEAL_DURATION_MINUTES（60）。
LUNCH_DURATION_MINUTES = 90
LUNCH_DURATION_FLOOR_MINUTES = 30
LUNCH_START_EARLIEST = time(11, 30)
LUNCH_START_LATEST = time(12, 30)
TOP_N_RECOMMENDATIONS = 3
WALK_METERS_PER_MINUTE = 80.0  # ~4.8 km/h pedestrian estimate
RATING_WEIGHT = 0.1  # rating * weight is subtracted from detour score
# Fixed tail rank for candidates we cannot geo-locate (and for the
# degenerate no-route-points case, where on-the-way-ness is undefined).
NO_LOCATION_DETOUR_SCORE = 999.0

# 跨城错排闸（2026-10-31「上海→西安→上海→西安」案）：候选池按调用方
# 所传城市检索，城市传错时整池都在几百公里外，rank_by_detour 只能在
# 错池内部排序、救不回来。有当日动线坐标时，已知坐标候选距动线
# ≥50km（跨城/远郊跨区）不算「顺路」，不推荐；无坐标候选无法判定，
# 维持排序垫底不动（行为不变）。
MEAL_DETOUR_HARD_KM = 50.0

# 午餐占位件 id 前缀（2026-10-31 拍板：午餐窗搜不到餐厅时插「午饭」占位）。
# 识别走 item_id 而非名字——名字随请求语言（lang_ctx.L）变化。
LUNCH_PLACEHOLDER_ID_PREFIX = "food-lunch-ph"
# 晚餐占位件 id 前缀（2026-11-07 用户指令「we need to hv dinner slot as
# well」：晚餐窗搜不到餐厅时同样占位保槽）。识别同走 item_id 前缀。
DINNER_PLACEHOLDER_ID_PREFIX = "food-dinner-ph"

# 荐点餐厅晚餐优先公里当量（2026-11-07 用户指令「those with special
# tags preferred to be set as dinner part」）：dinner 槽位排序时荐点标
# 候选（curated/ta/klook 等国际荐点）扣减的 detour 分值。3km ≈ 城内
# 常规顺路距离量级——同距内荐点稳赢、50km 硬闸仍兜底；lunch 不享受
# （用户指定晚餐场优先，午餐仍纯顺路语义）。
REC_DINNER_BONUS_KM = 3.0
# 仅晚市餐秀强拉力（2026-11-07 用户指令「restaurant 演出只有晚上应该
# 优先晚餐」）：时段闸锁死晚餐（allowed_slots=={dinner}）的荐点候选
# （红鼎宴类餐秀=目的地体验，食客本就要专程赴约）在 dinner 排序里
# 扣 10km——不是绝对优先（50km 硬闸 + 比它近 10km 以上的普通店仍能
# 赢），但压过城内常规顺路差。lunch 已被时段闸剔除，本档只影响 dinner。
REC_SHOW_DINNER_BONUS_KM = 10.0
# 荐点餐厅午餐顺路闸（2026-11-07 用户指令「餐厅也要考虑距离，如果
# 距离近可以放中午」）：点名店距午间动线 REC_LUNCH_NEAR_KM 内才进
# 午餐（顺路即午饭可吃），远了不硬灌午餐——留给晚餐（bonus 生效处），
# 避免唯一候选时 10km 外的点名店被午餐 pass 强吃。无坐标/无动线无法
# 判距时不裁（宁缺勿错的反面：无从判断就不预设远）。
REC_LUNCH_NEAR_KM = 3.0


def is_lunch_placeholder(item: VisitItem) -> bool:
    """True for the auto-inserted lunch placeholder (never a real POI)."""
    return item.item_id.startswith(LUNCH_PLACEHOLDER_ID_PREFIX)


def is_dinner_placeholder(item: VisitItem) -> bool:
    """True for the auto-inserted dinner placeholder (never a real POI)."""
    return item.item_id.startswith(DINNER_PLACEHOLDER_ID_PREFIX)


def _norm_name(s: object) -> str:
    """并池去重键：去空白 + lower（跨源同名不同写法兜底归并）。"""
    return re.sub(r"\s+", "", str(s or "")).lower()


_RESTAURANT_KEYWORD = "餐厅"


def amap_category_is_food(category: object) -> bool:
    """amap typecode strings look like「餐饮服务;中餐厅;…」; POI 底库
    骨架行直接存 food/attraction（底库落实链路 2026-10-24）。"""
    if not isinstance(category, str):
        return False
    if category.strip().lower() == "food":
        return True
    if category.strip().lower() == "attraction":
        return False
    return any(k in category for k in ("餐饮", "美食", "餐厅"))


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
    # DB 荐点标候选（2026-11-07 并池）：curated/ta/klook 等国际荐点的
    # 餐饮行——dinner 槽位享 REC_DINNER_BONUS_KM 排序优先。
    rec_tagged: bool = False
    # 时段要求（2026-11-07 用户指令「check if there is timing
    # requirement」）：营业时间/宜X时段推得出仅晚市（餐秀/夜市）→
    # 只进 dinner；仅早市 → 只进 lunch；推不出 → 两槽皆可。
    allowed_slots: frozenset[str] = frozenset({"lunch", "dinner"})
    # DB 建议时长（餐秀类 ~120min）：入卡时长 hint，钳制在窗内。
    duration_hint: int | None = None


def _allowed_slots_for(
    opening_hours: object, best_visit_time: object
) -> frozenset[str]:
    """由营业时间 / best_visit_time 推槽位适性（详见候选字段注释）。"""
    slot = infer_slot_from_hours(
        opening_hours if isinstance(opening_hours, str) else None
    )
    if slot == "evening":
        return frozenset({"dinner"})
    if slot == "morning":
        return frozenset({"lunch"})
    bvt = str(best_visit_time or "").strip().lower()
    if bvt in ("evening", "show", "night"):
        return frozenset({"dinner"})
    if bvt == "morning":
        return frozenset({"lunch"})
    return frozenset({"lunch", "dinner"})


def candidate_from_poi_dict(poi: dict) -> RestaurantCandidate | None:
    """POI 底库 hit（recommendation_food_in_city 形状）→ 候选并池件。

    location 兼容 DB hit 的 (lon, lat) 元组与图商的 {"lon","lat"} dict；
    rec_tagged 由调用方 store 显式标注（本层不重复实现荐点标判定）。
    """
    name = poi.get("name")
    if not name:
        return None
    raw_loc = poi.get("location")
    location = None
    if isinstance(raw_loc, dict):
        lon, lat = _as_float(raw_loc.get("lon")), _as_float(raw_loc.get("lat"))
        if lon is not None and lat is not None:
            location = GeoPoint(lon=lon, lat=lat)
    elif isinstance(raw_loc, (tuple, list)) and len(raw_loc) >= 2:
        lon, lat = _as_float(raw_loc[0]), _as_float(raw_loc[1])
        if lon is not None and lat is not None:
            location = GeoPoint(lon=lon, lat=lat)
    hint = _as_float(poi.get("suggested_duration_min"))
    return RestaurantCandidate(
        name=str(name),
        poi_id=poi.get("source_poi_id") or None,
        location=location,
        address=poi.get("address"),
        opening_hours=poi.get("opening_hours"),
        rating=_as_float(poi.get("rating")),
        biz_type=poi.get("category"),
        rec_tagged=bool(poi.get("rec_tagged")),
        allowed_slots=_allowed_slots_for(
            poi.get("opening_hours"), poi.get("best_visit_time")
        ),
        duration_hint=int(hint) if hint else None,
    )


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
        # 品类闸：关键词搜索偶气回非餐饮 POI（商场/景点），一律不当年
        # 餐厅推荐（外滩案 2026-10-31：松散候选源把出发城已删景点又排
        # 成午餐）。category 缺失（老数据）放行，有值即须是餐饮。
        raw_category = poi.get("category") or poi.get("biz_type")
        if raw_category and not amap_category_is_food(raw_category):
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
                allowed_slots=_allowed_slots_for(
                    poi.get("opening_hours"), poi.get("best_visit_time")
                ),
            )
        )
    return candidates


def meal_window(day: DayPlan, slot: MealSlot) -> tuple[time, time] | None:
    """Free gap of the meal window on that day (iron rule 20).

    Window constant minus the time coverage of existing items (end_time,
    or start+duration when end is missing; untimed items do not block).
    Untimed day -> the window constant as-is. Of the remaining gaps the
    largest one that still fits the slot's meal duration (lunch 90 min,
    2026-11-03 拍板; dinner 60) wins (ties -> earliest); fully occupied
    (or no gap fits a meal) -> None — no free gap means no forced
    insertion.
    """
    win_start, win_end = MEAL_WINDOWS[slot]
    ws, we = _minutes(win_start), _minutes(win_end)
    meal_dur = LUNCH_DURATION_MINUTES if slot == "lunch" else MEAL_DURATION_MINUTES
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
    gaps = [(s, e) for s, e in gaps if e - s >= meal_dur]
    if not gaps:
        return None
    best = max(gaps, key=lambda g: (g[1] - g[0], -g[0]))
    return (_time_of(best[0]), _time_of(best[1]))


def meal_times(
    window: tuple[time, time], duration: int = MEAL_DURATION_MINUTES
) -> tuple[time, time]:
    """Start/end of a meal inside a free gap (clamped midpoint).

    Midpoint of the gap, pulled back so start + duration never spills past
    the gap end: the 90-minute lunch window's midpoint lands at 12:45 and
    12:45+60 would overflow to 13:45, and so would any compressed gap
    shorter than two hours. For windows of at least one meal the result
    always satisfies window[0] <= start and end <= window[1].
    """
    mid = (_minutes(window[0]) + _minutes(window[1])) // 2
    start = max(_minutes(window[0]), min(mid, _minutes(window[1]) - duration))
    return _time_of(start), _time_of(start + duration)


def rank_by_detour(
    candidates: list[RestaurantCandidate],
    *,
    route_points: list[GeoPoint],
    dinner_rec: bool = False,
) -> list[RestaurantCandidate]:
    """Sort candidates by on-the-way-ness (smaller final score first).

    detour_score = km from the candidate to its nearest route point
    (min haversine over all points). Unlocatable candidates — and the
    degenerate no-route-points case — get the fixed tail score
    NO_LOCATION_DETOUR_SCORE. Final score = detour_score - rating *
    RATING_WEIGHT when a rating exists, so better-rated places win ties
    and near-ties. dinner_rec（2026-11-07 用户指令）：dinner 槽位荐点标
    候选扣 REC_DINNER_BONUS_KM，其中仅晚市餐秀（时段闸锁死晚餐）扣
    REC_SHOW_DINNER_BONUS_KM 强拉力——同距内稳赢，50km 硬闸仍兜底。
    Candidates' detour_score is populated in place.
    """
    for cand in candidates:
        if cand.location is None or not route_points:
            cand.detour_score = NO_LOCATION_DETOUR_SCORE
        else:
            meters = min(_haversine_m(cand.location, p) for p in route_points)
            cand.detour_score = meters / 1000.0

    def final_score(cand: RestaurantCandidate) -> float:
        bonus = cand.rating * RATING_WEIGHT if cand.rating is not None else 0.0
        rec = 0.0
        if dinner_rec and cand.rec_tagged:
            # 仅晚市餐秀（时段闸锁死晚餐）强拉力，其余荐点常规拉力
            rec = (
                REC_SHOW_DINNER_BONUS_KM
                if cand.allowed_slots == frozenset({"dinner"})
                else REC_DINNER_BONUS_KM
            )
        return cand.detour_score - bonus - rec

    return sorted(candidates, key=final_score)


def build_food_item(
    candidate: RestaurantCandidate,
    *,
    day: int,
    city: str,
    window: tuple[time, time],
    item_id: str,
    duration: int = MEAL_DURATION_MINUTES,
) -> VisitItem:
    """Convert a ranked candidate into an addable food VisitItem.

    start/end = meal_times(window, duration): the free-gap midpoint clamped
    so the meal stays inside the gap, unpinned (iron rule 20: never
    displaces user-confirmed items, rule 19 stays intact). Final
    non-overlap is guaranteed by validate_plan in the caller's mutation
    pipeline, not here.
    """
    start, end = meal_times(window, duration)
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
        start_time=start,
        end_time=end,
        duration_minutes=duration,
        pinned=False,
    )


async def recommend_restaurants(
    amap_client: AmapSearchService | None,
    day_plan: DayPlan,
    slot: MealSlot,
    *,
    city: str | None = None,
    window: tuple[time, time] | None = None,
    extra_pois: list[dict] | None = None,
) -> list[VisitItem]:
    """Top-N ready-to-add food items for the meal slot (§6.2 v1.7).

    Pipeline: meal_window (no free gap -> [], iron rule 20: never force a
    meal into an occupied slot) -> search_restaurants (amap failure -> [])
    -> rank_by_detour (route = that day's located VisitItems) ->
    build_food_item (unpinned, inside the gap). The caller inserts the
    returned items via apply_diffs and relies on validate_plan for rules
    1/2 (non-overlap, poi_hours) — see module docstring for the split.

    `window` overrides the derived free gap for callers that already
    resolved a concrete placement slot themselves (plan.py lunch pass:
    the slot may sit after an overrunning transfer, outside the raw
    window) — the iron-rule-20 gap check is then the caller's duty.
    Lunch items carry the 2026-11-03 lunch duration default (90 min);
    dinner keeps the generic one-hour meal.

    `extra_pois`（2026-11-07 用户指令「有标记推荐的没进槽位…FIX IT」）：
    DB 荐点餐厅（curated/ta/klook 标的 food 行，recommendation_food_in_city
    供给）与图商实时检索并池——我们点名的店（红鼎宴/失重餐厅类）live
    amap 关键词搜索覆盖不到。并池去重：归一名碰撞时图商实时字段
    （坐标/营业时间更鲜）赢、荐点标 OR 归并；时段要求闸按槽位裁剪
    （仅晚市餐秀不进午餐窗）；dinner 槽位荐点候选享排序优先
    （REC_DINNER_BONUS_KM）；DB 建议时长（餐秀 ~120min）作入卡时长
    hint，钳制在窗内。
    """
    window = window or meal_window(day_plan, slot)
    if window is None:
        return []
    duration = LUNCH_DURATION_MINUTES if slot == "lunch" else MEAL_DURATION_MINUTES
    city_used = city or day_plan.base_city
    candidates = await search_restaurants(amap_client, city_used)
    if extra_pois:
        by_name = {_norm_name(c.name): c for c in candidates}
        for poi in extra_pois:
            cand = candidate_from_poi_dict(poi)
            if cand is None or slot not in cand.allowed_slots:
                # 时段要求闸（2026-11-07）：仅晚市/仅早市店不进错槽。
                continue
            twin = by_name.get(_norm_name(cand.name))
            if twin is None:
                candidates.append(cand)
                by_name[_norm_name(cand.name)] = cand
            else:
                # 同名双源：图商实时字段保留，荐点标并回（去重不吞标）
                twin.rec_tagged = twin.rec_tagged or cand.rec_tagged
    # 当天已排的 POI 不再当餐厅推荐（同站景点不是用餐点；2026-10-31
    # 外滩案：松散候选源把已排景点又排成晚餐，造成同天双卡）
    planned_pids = {
        i.poi_id for i in day_plan.items if isinstance(i, VisitItem) and i.poi_id
    }
    candidates = [c for c in candidates if c.poi_id not in planned_pids]
    # 时段要求闸全池生效（2026-11-07）：仅晚市/仅早市店不进错槽——
    # 图商 live 候选与 DB 荐点候选同一把闸（营业时间回填后即生效）。
    candidates = [c for c in candidates if slot in c.allowed_slots]
    route_points = [
        item.location
        for item in day_plan.items
        if isinstance(item, VisitItem) and item.location is not None
    ]
    ranked = rank_by_detour(
        candidates, route_points=route_points, dinner_rec=slot == "dinner"
    )
    if route_points:
        # 有动线才有顺路语义：已知坐标的远距候选=跨城错排信号，整只
        # 剔除比在错池里排序更诚实（宁缺不插 700km 外的「顺路」店）。
        ranked = [
            r
            for r in ranked
            if r.location is None or r.detour_score < MEAL_DETOUR_HARD_KM
        ]
    if slot == "lunch":
        # 荐点餐厅午餐顺路闸（2026-11-07 用户指令「餐厅也要考虑距离，
        # 如果距离近可以放中午」）：点名店距午间动线 REC_LUNCH_NEAR_KM
        # 内才进午餐，远了不硬灌——留给晚餐（bonus 生效处），否则唯一
        # 候选时 10km 外的点名店会被午餐 pass 强吃。无坐标/无动线无从
        # 判距不裁。
        ranked = [
            r
            for r in ranked
            if not r.rec_tagged
            or r.location is None
            or not route_points
            or r.detour_score < REC_LUNCH_NEAR_KM
        ]
    span = _minutes(window[1]) - _minutes(window[0])
    out: list[VisitItem] = []
    for index, cand in enumerate(ranked[:TOP_N_RECOMMENDATIONS]):
        eff_duration = duration
        if cand.duration_hint:
            # DB 建议时长（餐秀 120min 类）作 hint：默认档起底、窗宽封顶
            # （gap < hint 时缩到 gap，绝不溢出铁律 20 空窗）。
            eff_duration = min(max(duration, cand.duration_hint), span)
        out.append(
            build_food_item(
                cand,
                day=day_plan.day,
                city=city_used,
                window=window,
                item_id=f"food-d{day_plan.day}-{slot}-{index + 1}",
                duration=eff_duration,
            )
        )
    return out
