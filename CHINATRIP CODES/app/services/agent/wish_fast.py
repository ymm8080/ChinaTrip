"""一句话加心愿的确定性落位（2026-11-13 用户拍板，延迟收口）。

用户原话口径：一句话加心愿不该等一分钟——「once we get 心愿单，we will
check its location and decide which cluster it belongs to, then go to
that cluster and date, and remove according to location and priority」。

旧链路每一句「我要去豫园」都当结构性重排：编辑 LLM 一轮（5-7s）+ CP 全量
重解（~15s）+ 全量富化（5-8s），线上实测 38s。本模块把这条路改成全确定性：

    名字解析（POI 底库，纯 DB）→ 同城地理簇择日（_geo_cluster_day）
    → 就近插位 → 当天列表序时刻顺排（_fallback_sequence_times）
    → 装不下时按「档号大=弱、离新点远」让位（record 进 plan.unplaced）
    → 库读详情（地址/营业时间/英文名，零外呼）→ annotate_legs → 校验

只在「单点、专名、同城、能解析到唯一 POI」时接管；任何一步不满足前提
（多点/带其它动作/查不到/异地/校验新增硬伤）返回 None，交回 LLM 主车道
——口径仍是「宁可慢不可错」。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

from app.services.agent.hotel_stays import reanchor_hotel_cards
from app.services.itinerary import (
    GeoPoint,
    ItineraryPlan,
    RuleSeverity,
    VisitItem,
    annotate_legs,
    haversine_km,
    validate_plan,
)
from app.services.itinerary.models import UnplacedCandidate
from app.services.lang_ctx import L
from app.services.llm import ChatMessage

logger = logging.getLogger(__name__)

#: 只接管短句（长句多半带别的诉求，交主车道）
_MAX_TEXT_CHARS = 32
#: 让位上限（同一天最多挤掉几张低档卡）
_MAX_EVICT = 3

#: 句子里出现这些词就不是「单点加心愿」——其它动作/条件交 LLM 主车道
_BLOCKERS = (
    "改",
    "删",
    "移",
    "挪",
    "换",
    "提前",
    "推迟",
    "重排",
    "取消",
    "不去",
    "不想去",
    "预算",
    "票",
    "链接",
    "http",
    "怎么去",
    "几点",
    "翻译",
    "天气",
    "规划",
    "推荐",
    "附近",
)
#: 多点句（「豫园和外滩」）同样交主车道
_MULTI_PLACE = re.compile(r"、|或者|还是|以及")
_DAYS_PHRASE = re.compile(r"\d+\s*天|[一二三四五六七八九十两]+\s*天")

_ZH_GO = re.compile(
    r"^(?:请|麻烦)?(?:帮我)?(?:我)?(?:想|要|打算|计划|准备)?"
    r"(?:去|到|参观|游览|逛逛|逛|看看|打卡)(?P<name>.+)$"
)
_ZH_ADD = re.compile(
    r"^(?:请|麻烦)?(?:帮我)?(?:把|将)?(?P<name>.+?)"
    r"(?:加|添|放|排)(?:到|进|入)(?:我的)?(?:行程|计划|路线)(?:里|中|里边|里面)?$"
)
_ZH_ADD2 = re.compile(
    r"^(?:请|麻烦)?(?:帮我)?(?:加|添加|加上|新增|安排)(?:一下|下|一个|个)?(?P<name>.+)$"
)
# 餐饮→午/晚餐卡（2026-11-13 用户拍板「餐饮可以作为午餐晚餐的心愿单」）
_ZH_EAT = re.compile(
    r"^(?:请|麻烦)?(?:帮我)?(?:我)?(?:想|要|打算|计划)?"
    r"(?:吃|尝尝|试一试|试试)(?P<name>.+)$"
)
# 酒店→HOTEL 卡（2026-11-13 用户拍板「酒店可以是 HOTEL 卡的心愿单」）
_ZH_STAY = re.compile(
    r"^(?:请|麻烦)?(?:帮我)?(?:我)?(?:想|要|打算|计划)?"
    r"(?:住|入住|住在)(?P<name>.+)$"
)
_EN_GO = re.compile(
    r"^(?:please\s+)?(?:i\s+(?:want|would\s+like|'d\s+like)\s+to\s+"
    r"(?:go\s+to|visit|see)|(?:go\s+to|visit|see))\s+(?P<name>.+)$",
    re.IGNORECASE,
)
_EN_ADD = re.compile(
    r"^(?:please\s+)?(?:add|include)\s+(?P<name>.+?)(?:\s+(?:to|into)\s+"
    r"(?:my\s+)?(?:trip|itinerary|plan))?$",
    re.IGNORECASE,
)
_PATTERNS = (_ZH_ADD, _ZH_GO, _ZH_EAT, _ZH_STAY, _ZH_ADD2, _EN_ADD, _EN_GO)

_GENERIC_NAMES = frozenset(
    {
        "景点",
        "行程",
        "计划",
        "这里",
        "那里",
        "附近",
        "城市",
        "地方",
        "好玩的地方",
        "景点",
    }
)
_TRAIL_PARTICLES = ("吧", "呢", "呀", "啊", "哦", "啦", "谢谢", "好吗", "可以吗")
_STRIP_CHARS = " \t\r\n，。,.!?！？；;、：:\"'“”‘’【】[]()（）"

#: 快路径回合标记（session_id）：端点据此跳过整趟实测腿刷新——落位时已
#: 按直线估算标注，动线实测交给下一次编辑/打开行程（2026-11-13 延迟收口：
#: 图商惩罚/配额死时 refresh_legs 单回合可拖 30s+，用户感受到的就是「慢」）。
_FAST_TURNS: set[str] = set()
_MAX_FAST_TURNS = 256


def _mark_fast_turn(session) -> None:
    sid = getattr(session, "session_id", "") or ""
    if not sid:
        return
    if len(_FAST_TURNS) >= _MAX_FAST_TURNS:
        _FAST_TURNS.clear()
    _FAST_TURNS.add(sid)


def consume_fast_turn(session_id: str | None) -> bool:
    """端点侧消费一次快路径标记（True = 本回合跳过实测腿刷新）。"""
    sid = session_id or ""
    if sid in _FAST_TURNS:
        _FAST_TURNS.discard(sid)
        return True
    return False


@dataclass
class WishPlacement:
    """落位结果（plan 是深拷贝，调用方确认后才写回会话）。"""

    plan: ItineraryPlan
    day: int
    item: VisitItem
    neighbour_name: str | None = None
    neighbour_km: float | None = None
    removed: list[VisitItem] = field(default_factory=list)
    #: sight（景点卡）/ food（午晚餐卡）/ hotel（住宿卡）
    kind: str = "sight"
    #: 酒店：同段住宿一并写上的卡数
    synced_cards: int = 0


def _clean_name(raw: str) -> str:
    text = (raw or "").strip(_STRIP_CHARS)
    changed = True
    while changed and text:
        changed = False
        for tail in _TRAIL_PARTICLES:
            if text.endswith(tail) and len(text) > len(tail):
                text = text[: -len(tail)].strip(_STRIP_CHARS)
                changed = True
    return text


def _multi_place_name(name: str) -> bool:
    """「豫园和外滩」是两点，「福和慧/和平饭店」是专名（和字在词里）。
    只在分隔两侧都是 ≥2 字时才当并列。"""
    for sep in ("和", "与"):
        if sep in name:
            parts = name.split(sep)
            if len(parts) >= 2 and all(len(part) >= 2 for part in parts):
                return True
    return False


def _looks_like_place(name: str) -> bool:
    if not (2 <= len(name) <= 24):
        return False
    if name in _GENERIC_NAMES:
        return False
    # 名字里带分隔标点 = 多句话（「豫园，顺便吃…」），不当单点心愿
    if any(ch in name for ch in "，。,.!?！？；;：:、"):
        return False
    if _multi_place_name(name):
        return False
    if not any(ch.isalnum() for ch in name):
        return False
    return True


def parse_place_request(text: str) -> str | None:
    """「我要去豫园」/「add Yu Garden」→「豫园」；不是单点口吻 → None。"""
    raw = (text or "").strip()
    if not raw or len(raw) > _MAX_TEXT_CHARS:
        return None
    if any(token in raw for token in _BLOCKERS):
        return None
    if _MULTI_PLACE.search(raw) or _DAYS_PHRASE.search(raw):
        return None
    for pattern in _PATTERNS:
        match = pattern.match(raw)
        if not match:
            continue
        name = _clean_name(match.group("name"))
        if _looks_like_place(name):
            return name
    return None


def _point(poi: dict | None) -> GeoPoint | None:
    loc = (poi or {}).get("location")
    if isinstance(loc, dict):
        lon, lat = loc.get("lon"), loc.get("lat")
        if lon is not None and lat is not None:
            return GeoPoint(lon=float(lon), lat=float(lat))
        return None
    if isinstance(loc, (tuple, list)) and len(loc) == 2:
        return GeoPoint(lon=float(loc[0]), lat=float(loc[1]))
    return None


def _city_eq(a: str | None, b: str | None) -> bool:
    left = (a or "").strip().removesuffix("市")
    right = (b or "").strip().removesuffix("市")
    return bool(left) and left == right


def _fallback_day(days) -> int:
    """无坐标可归族时的回退：当天已布参访最少的同城日（同数取低日号）。"""

    def _load(day) -> tuple[int, int]:
        visits = [
            it
            for it in day.items
            if isinstance(it, VisitItem)
            and (it.category or "") not in ("food", "hotel")
        ]
        return (len(visits), day.day)

    return min(days, key=_load).day


def _insert_position(day, location: GeoPoint | None) -> int:
    """就近插位：落在当天最近邻之后；无坐标件则压到末尾（酒店/夜卡之前）。"""
    items = day.items
    if location is not None:
        best_index: int | None = None
        best_km: float | None = None
        for index, item in enumerate(items):
            if not isinstance(item, VisitItem) or item.location is None:
                continue
            km = haversine_km(location, item.location)
            if best_km is None or km < best_km:
                best_km, best_index = km, index
        if best_index is not None:
            return best_index + 1
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if isinstance(item, VisitItem) and (item.category or "") == "hotel":
            return index
    return len(items)


def _is_removable(item: VisitItem) -> bool:
    """让位候选：非用户钉、非必去、非手建/精选、非餐宿卡。"""
    if not isinstance(item, VisitItem):
        return False
    if item.pinned or item.must or item.created or item.curated:
        return False
    if (item.category or "") in ("food", "hotel"):
        return False
    return True


def _victim_key(item: VisitItem, location: GeoPoint | None) -> tuple:
    """优先级弱 → 远 → 占时长的排前面（档号大=弱，2026-11-03 名录序）。"""
    tier = item.tier if item.tier is not None else 11
    km = 0.0
    if location is not None and item.location is not None:
        try:
            km = haversine_km(location, item.location)
        except Exception:
            km = 0.0
    return (tier, km, item.duration_minutes or 0)


def _pick_evictable(
    day, new_item: VisitItem, location: GeoPoint | None
) -> VisitItem | None:
    """当天让位候选：先挑已经排不上时刻的（它们本来就不合身），
    全排上了再按优先级挑最弱的一张——钉/必去/手建/精选/餐宿永不动。"""
    removable = [
        item for item in day.items if item is not new_item and _is_removable(item)
    ]
    if not removable:
        return None
    untimed = [item for item in removable if item.start_time is None]
    pool = untimed or removable
    return max(pool, key=lambda item: _victim_key(item, location))


def _build_item(
    *, item_id: str, name: str, poi: dict, city: str, day_no: int
) -> VisitItem:
    from app.services.agent import plan as plan_mod

    duration = poi.get("suggested_duration_min")
    try:
        minutes = int(duration) if duration else 0
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0:
        minutes = 90
    return VisitItem(
        item_id=item_id,
        name=str(poi.get("name") or name).strip() or name,
        poi_id=poi.get("source_poi_id"),
        category=str(poi.get("category") or "") or "sight",
        city=city,
        location=_point(poi),
        address=poi.get("address"),
        address_en=poi.get("address_en"),
        name_en=poi.get("name_en"),
        opening_hours=poi.get("opening_hours"),
        opening_hours_en=poi.get("opening_hours_en"),
        best_visit_time=poi.get("best_visit_time"),
        rain_ok=poi.get("rain_ok"),
        day=day_no,
        duration_minutes=minutes,
        tier=plan_mod._source_tier(poi),
    )


def place_wish(
    plan: ItineraryPlan,
    *,
    name: str,
    poi: dict,
    city: str,
    item_id: str,
) -> WishPlacement | None:
    """把新心愿落进「地理簇所在天」并顺排；该天挤不下就按距离退同城其它天。

    纯计算（零 IO / 零 LLM）：所有同城天都挤不出时段 → None（调用方回主车道）。
    """
    location = _point(poi)
    city_days = [d for d in plan.days if _city_eq(d.base_city, city)]
    pool = city_days or list(plan.days)
    if not pool:
        return None
    for day_no in _rank_days(pool, location):
        placement = _place_on_day(
            plan, day_no=day_no, name=name, poi=poi, city=city, item_id=item_id
        )
        if placement is not None:
            return placement
    logger.info("plan: fast wish no slot for %s in %s", name, city)
    return None


def _rank_days(days, location: GeoPoint | None) -> list[int]:
    """同城候选日：越近的簇越先试（同距按日号）；无坐标→少参访日先试。"""
    if location is None:
        fallback = _fallback_day(days)
        return [fallback] + [d.day for d in days if d.day != fallback]
    scored: list[tuple[float, int]] = []
    for day in days:
        points = [
            item.location
            for item in day.items
            if isinstance(item, VisitItem) and item.location is not None
        ]
        km = min((haversine_km(location, p) for p in points), default=1e6)
        scored.append((km, day.day))
    scored.sort()
    return [day for _km, day in scored]


def _insert_positions(day, location: GeoPoint | None) -> list[int]:
    """插位候选：最近邻之后 → 最近邻之前 → 队尾（先试不让位的）。"""
    items = day.items
    after = _insert_position(day, location)
    positions = [after]
    before = after - 1
    if 0 <= before < len(items):
        positions.append(before)
    positions.append(len(items))
    ordered: list[int] = []
    for pos in positions:
        if pos not in ordered and 0 <= pos <= len(items):
            ordered.append(pos)
    return ordered


def _place_on_day(
    plan: ItineraryPlan,
    *,
    day_no: int,
    name: str,
    poi: dict,
    city: str,
    item_id: str,
) -> WishPlacement | None:
    """同一天先试两个插位：能不让位就不让位，实在装不下才按优先级让位。"""
    day = next((d for d in plan.days if d.day == day_no), None)
    if day is None:
        return None
    best: WishPlacement | None = None
    for position in _insert_positions(day, _point(poi)):
        placement = _attempt_on_day(
            plan,
            day_no=day_no,
            position=position,
            name=name,
            poi=poi,
            city=city,
            item_id=item_id,
        )
        if placement is None:
            continue
        if not placement.removed:
            return placement
        if best is None or len(placement.removed) < len(best.removed):
            best = placement
    return best


def _schedule_existing(
    plan: ItineraryPlan, item_id: str, *, city: str
) -> WishPlacement | None:
    """已在册但没时刻的心愿：就地补位（挤不下再按优先级让位），
    本天满再按距离退同城其它天——不重跑 LLM。"""
    existing = next(
        (
            item
            for day in plan.days
            for item in day.items
            if getattr(item, "item_id", "") == item_id
        ),
        None,
    )
    if existing is None:
        return None
    location = existing.location
    city_days = [d for d in plan.days if _city_eq(d.base_city, city)] or list(plan.days)
    order = [d.day for d in city_days if d.day == existing.day]
    order += [day for day in _rank_days(city_days, location) if day not in order]
    best: WishPlacement | None = None
    for day_no in order:
        for position in _insert_positions(
            next((d for d in plan.days if d.day == day_no), plan.days[0]), location
        ):
            placement = _attempt_on_day(
                plan,
                day_no=day_no,
                position=position,
                name=existing.name,
                poi={},
                city=city,
                item_id=item_id,
                existing_item_id=item_id,
            )
            if placement is None:
                continue
            if not placement.removed:
                return placement
            if best is None or len(placement.removed) < len(best.removed):
                best = placement
    return best


def _attempt_on_day(
    plan: ItineraryPlan,
    *,
    day_no: int,
    position: int,
    name: str,
    poi: dict,
    city: str,
    item_id: str,
    existing_item_id: str | None = None,
) -> WishPlacement | None:
    from app.services.agent import plan as plan_mod

    candidate = plan.model_copy(deep=True)
    location = _point(poi)
    day = next((d for d in candidate.days if d.day == day_no), None)
    if day is None:
        return None
    position = max(0, min(position, len(day.items)))
    if existing_item_id is not None:
        item = next(
            (
                other
                for other in day.items
                if isinstance(other, VisitItem) and other.item_id == existing_item_id
            ),
            None,
        )
        if item is None:
            # 他天拎过来（该天装不下时的退天）
            source = next(
                (
                    (dp, other)
                    for dp in candidate.days
                    for other in dp.items
                    if isinstance(other, VisitItem)
                    and other.item_id == existing_item_id
                ),
                None,
            )
            if source is None:
                return None
            src_day, item = source
            src_day.items.remove(item)
            item.day = day_no
            day.items.insert(position, item)
    else:
        item = _build_item(
            item_id=item_id, name=name, poi=poi, city=city, day_no=day_no
        )
        day.items.insert(position, item)
    # 当天非钉件时刻清空 → 列表序顺排（新件按最近邻插位，与拖拽同口径）
    for other in day.items:
        if other is item or not isinstance(other, VisitItem):
            continue
        if other.pinned or other.soft_pin:
            continue
        other.start_time = None
        other.end_time = None
    plan_mod._fallback_sequence_times(candidate, keep_list_order=True)
    removed = _evict_until_clean(candidate, day, item, location)
    if removed is None:
        logger.info("plan: fast wish no slot for %s on day %s", name, day_no)
        return None
    item.must = True
    item.pinned = True
    # 邻伴在让位之后再算：被撤掉的卡不能再写成「贴着它」（文案自相矛盾）
    neighbour_name = None
    neighbour_km = None
    for other in day.items:
        if other is item or not isinstance(other, VisitItem):
            continue
        if location is None or other.location is None:
            continue
        km = haversine_km(location, other.location)
        if neighbour_km is None or km < neighbour_km:
            neighbour_km, neighbour_name = km, other.name
    annotate_legs(candidate)
    reanchor_hotel_cards([day], keep_ids={item.item_id})
    return WishPlacement(
        plan=candidate,
        day=day_no,
        item=item,
        neighbour_name=neighbour_name,
        neighbour_km=neighbour_km,
        removed=removed,
    )


def _evict_until_clean(
    plan: ItineraryPlan, day, new_item: VisitItem, location: GeoPoint | None
) -> list[VisitItem] | None:
    """把当天排不上时刻的弱件按「档号大=弱、远者先走」逐张让出，直到当天
    全部有时刻；让位件记入 plan.unplaced（H5 可替换 chips）。
    返回 None = 让位到顶仍有未排件（整日真装不下，交回主车道）。"""
    from app.services.agent import plan as plan_mod

    removed: list[VisitItem] = []
    while len(removed) < _MAX_EVICT:
        untimed = [
            other
            for other in day.items
            if isinstance(other, VisitItem) and other.start_time is None
        ]
        if not untimed:
            break
        victim = _pick_evictable(day, new_item, location)
        if victim is None:
            break
        day.items.remove(victim)
        removed.append(victim)
        plan.unplaced.append(
            UnplacedCandidate(
                name=victim.name,
                name_en=victim.name_en,
                poi_id=victim.poi_id,
                category=victim.category,
                tier=victim.tier,
                duration_minutes=victim.duration_minutes,
            )
        )
        plan_mod._fallback_sequence_times(plan, keep_list_order=True)
    untimed = [
        other
        for other in day.items
        if isinstance(other, VisitItem) and other.start_time is None
    ]
    if new_item.start_time is None or untimed:
        return None
    return removed


def place_food(
    agent, session, *, name: str, poi: dict, city: str, item_id: str
) -> WishPlacement | None:
    """点名餐厅 → 午/晚餐卡（2026-11-13 用户拍板：餐饮就是午晚餐心愿）。

    复用生成侧的 `_food_visit`（按坐标归族择日、让位自动餐件、餐窗锚定），
    写入后再顺排当天、装不下按优先级让位。"""
    from app.services.agent import plan as plan_mod

    candidate = session.plan.model_copy(deep=True)
    view = session.model_copy(update={"plan": candidate})
    location = _point(poi)
    item = agent._food_visit(
        view,
        name=str(poi.get("name") or name).strip() or name,
        city=city,
        location=location,
        poi_id=poi.get("source_poi_id"),
        item_id=item_id,
    )
    day = next((d for d in candidate.days if d.day == item.day), None)
    if day is None:
        return None
    for other in day.items:
        if other is item or not isinstance(other, VisitItem):
            continue
        if other.pinned or other.soft_pin:
            continue
        other.start_time = None
        other.end_time = None
    day.items.append(item)
    plan_mod._fallback_sequence_times(candidate, keep_list_order=True)
    removed = _evict_until_clean(candidate, day, item, location)
    if removed is None:
        return None
    item.must = True
    annotate_legs(candidate)
    reanchor_hotel_cards([day], keep_ids={item.item_id})
    return WishPlacement(
        plan=candidate, day=day.day, item=item, removed=removed, kind="food"
    )


def _minutes_of(value) -> int | None:
    if value is None:
        return None
    return value.hour * 60 + value.minute


def _retime_night_cards(days) -> None:
    """酒店换点后把当晚卡顺延到「末件散场 + 真实车程」——否则新的
    酒店地址会凭空多出一条铁律 7 硬伤（真实案例：36 分钟车程而卡还在
    30 分钟后开场）。"""
    import datetime as _dt

    from app.services.agent.hotel_stays import is_hotel_night
    from app.services.itinerary.rules import travel_gap_needed

    for day in days:
        night = next(
            (
                item
                for item in day.items
                if isinstance(item, VisitItem) and is_hotel_night(item)
            ),
            None,
        )
        if night is None or night.start_time is None:
            continue
        prev = None
        for item in day.items:
            if item is night or not isinstance(item, VisitItem):
                continue
            if item.end_time is None or item.start_time is None:
                continue
            if prev is None or item.start_time > prev.start_time:
                prev = item
        if prev is None or prev.end_time > night.start_time:
            continue
        need = travel_gap_needed(prev, night)
        if need is None:
            continue
        start = _minutes_of(night.start_time)
        target = _minutes_of(prev.end_time) + need
        if start is None or target <= start:
            continue
        duration = night.duration_minutes or 60
        if target + duration > 24 * 60:
            target = 24 * 60 - duration - 1
        night.start_time = _dt.time(target // 60, target % 60)
        night.end_time = _dt.time((target + duration) // 60, (target + duration) % 60)


def place_hotel(plan: ItineraryPlan, *, name: str, poi: dict) -> WishPlacement | None:
    """点名酒店 → HOTEL 卡（2026-11-13 用户拍板：酒店是住宿卡心愿）。

    写第一晚夜卡的酒店身份，再由 sync_hotel_stay 铺开整段住宿（夜卡↔晨卡
    对 + 同段尚未验证的占位卡）；已写上别家的卡不动。"""
    from app.services.agent.hotel_stays import is_hotel_night, sync_hotel_stay

    candidate = plan.model_copy(deep=True)
    nights = [
        item
        for day in candidate.days
        for item in day.items
        if isinstance(item, VisitItem) and is_hotel_night(item)
    ]
    if not nights:
        return None
    location = _point(poi)
    target = nights[0]
    if location is not None:
        located = [c for c in nights if c.location is not None]
        if located:
            target = min(located, key=lambda c: haversine_km(location, c.location))
    card_name = str(poi.get("name") or name).strip()
    target.name = card_name
    target.poi_id = poi.get("source_poi_id")
    target.category = "hotel"
    if poi.get("address"):
        target.address = poi["address"]
    if poi.get("address_en"):
        target.address_en = poi["address_en"]
    if poi.get("opening_hours"):
        target.opening_hours = poi["opening_hours"]
    if location is not None:
        target.location = location
    _pair, filled = sync_hotel_stay(candidate.days, target, hotel_name=card_name)
    reanchor_hotel_cards(candidate.days)
    _retime_night_cards(candidate.days)
    annotate_legs(candidate)
    return WishPlacement(
        plan=candidate,
        day=target.day,
        item=target,
        kind="hotel",
        synced_cards=filled,
    )


def _hard_messages(plan: ItineraryPlan) -> set[str]:
    report = validate_plan(plan, poi_hours=[])
    return {
        violation.message
        for violation in report.violations
        if violation.severity is RuleSeverity.error
    }


def _poi_kind(poi: dict) -> str:
    """品类分流（2026-11-13 用户拍板「餐饮可以作为午餐晚餐的心愿单，
    酒店可以是 HOTEL 卡的心愿单」）：sight→景点卡，food→午/晚餐卡，
    hotel→住宿卡；机场/车站等仍交回主车道。"""
    from app.services.restaurants import amap_category_is_food

    category = str(poi.get("category") or "").strip().lower()
    if "hotel" in category or "酒店" in category or "住宿" in category:
        return "hotel"
    if category == "food" or amap_category_is_food(category):
        return "food"
    blocked = ("airport", "train", "subway", "metro", "station", "port")
    if any(token in category for token in blocked):
        return "other"
    return "sight"


def _name_close(wanted: str, found: str) -> bool:
    left = re.sub(r"\s+", "", wanted or "")
    right = re.sub(r"\s+", "", found or "")
    if not left or not right:
        return False
    return left == right or left in right or right in left


async def _with_details(agent, poi: dict) -> dict:
    """库读补齐双语字段/地址/营业时间（零外呼）——快路径不做全量富化，
    但卡片展示字段不能缺（2026-11-13：只查这一条）。"""
    poi_id = poi.get("source_poi_id")
    store = getattr(agent, "_poi_details", None)
    if not poi_id or store is None:
        return poi
    try:
        detail = await asyncio.to_thread(store.get, str(poi_id))
    except Exception:
        logger.warning("plan: fast wish detail read failed", exc_info=True)
        detail = None
    if not detail:
        return poi
    merged = dict(poi)
    for key in (
        "name_en",
        "address",
        "address_en",
        "opening_hours",
        "opening_hours_en",
        "intro_en",
    ):
        if not merged.get(key) and detail.get(key):
            merged[key] = detail[key]
    return merged


async def _exact_poi(agent, city: str, name: str) -> dict | None:
    """底库精确同名（不受「核心词包含」兜底影响——脏行「住XX酒店」
    曾把真酒店顶掉，2026-11-13 实弹）。"""
    store = getattr(agent, "_poi_details", None)
    if store is None:
        return None
    try:
        hits = await asyncio.to_thread(store.search_keyword, city, [name])
    except Exception:
        logger.warning("plan: fast wish exact lookup failed", exc_info=True)
        return None
    exact = [
        hit for hit in hits or [] if (hit.get("name") or "").strip() == name.strip()
    ]
    if not exact:
        return None
    exact.sort(key=lambda hit: hit.get("location") is None)
    return exact[0]


async def _resolve_poi(agent, session, name: str):
    """专名 → (poi, city)：先底库精确同名，再底库模糊，再图商（同名）。"""
    cities = [c for c in dict.fromkeys(session.cities or []) if (c or "").strip()]
    for city in cities:
        poi = await _exact_poi(agent, city, name)
        if poi:
            return poi, str(poi.get("city") or city).strip() or city
    lookup = getattr(agent, "_poi_library_lookup", None)
    if lookup is not None:
        for city in cities:
            try:
                poi = await lookup(session, name, None, city)
            except Exception:
                logger.warning("plan: fast wish library lookup failed", exc_info=True)
                poi = None
            if poi:
                return poi, str(poi.get("city") or city).strip() or city
    lookup_net = getattr(agent, "_lookup_poi", None)
    if lookup_net is not None:
        for city in cities:
            try:
                poi = await lookup_net(name, city)
            except Exception:
                logger.warning("plan: fast wish poi search failed", exc_info=True)
                poi = None
            if poi and _name_close(name, str(poi.get("name") or "")):
                return poi, city
    return None, None


def _already_reply(item: VisitItem) -> str:
    when = (
        f"{item.start_time.strftime('%H:%M')}-{item.end_time.strftime('%H:%M')}"
        if item.start_time is not None and item.end_time is not None
        else ""
    )
    return L(
        f"「{item.name}」已经在第{item.day}天 {when} 了，无需改动。",
        f'"{item.name}" is already on day {item.day} at {when} — nothing to change.',
    )


def _placed_reply(placement: WishPlacement) -> str:
    item = placement.item
    when = (
        f"{item.start_time.strftime('%H:%M')}-{item.end_time.strftime('%H:%M')}"
        if item.start_time is not None and item.end_time is not None
        else ""
    )
    if placement.kind == "hotel":
        address = f"（{item.address}）" if item.address else ""
        extra = ""
        if placement.synced_cards:
            extra = L(
                f"，同段住宿其余 {placement.synced_cards} 张卡已同步",
                f", synced {placement.synced_cards} more card(s) of this stay",
            )
        return L(
            f"已把住宿定为{item.name}{address}（第{placement.day}晚起{extra}）。",
            f"Stay set to {item.name}{address} (from night {placement.day}{extra}).",
        )
    if placement.kind == "food":
        meal = "午饭" if (item.start_time and item.start_time.hour < 16) else "晚饭"
        return L(
            f"已把{item.name}排进第{placement.day}天的{meal}卡（{when}）。",
            f"{item.name} is on day {placement.day}'s "
            f"{'lunch' if meal == '午饭' else 'dinner'} card ({when}).",
        )
    near = ""
    if placement.neighbour_name and (placement.neighbour_km or 0) <= 5.0:
        near = L(
            f"，贴着{placement.neighbour_name}（同片区）",
            f", next to {placement.neighbour_name} (same cluster)",
        )
    reply = L(
        f"已把{item.name}放进第{placement.day}天 {when}{near}。",
        f"Added {item.name} to day {placement.day} at {when}{near}.",
    )
    if placement.removed:
        names = "、".join(i.name for i in placement.removed)
        reply += L(
            f" 为腾时间，第{placement.day}天撤下了{names}"
            "（低优先级/离得远，已放进可替换候选）。",
            f" To make room, {names} came off day {placement.day}"
            " (lower priority / farther out; kept as swap candidates).",
        )
    return reply


def _category_matches(item: VisitItem, kind: str | None) -> bool:
    """同名件品类兼容闸：酒店心愿不能撞上一个叫「住XX酒店」的观光卡。"""
    from app.services.agent.hotel_stays import is_hotel_morning, is_hotel_night

    category = (item.category or "").strip()
    if kind == "hotel":
        return category == "hotel" or is_hotel_night(item) or is_hotel_morning(item)
    if kind == "food":
        return category == "food"
    if kind is None:
        return True
    return category not in ("food", "hotel")


def _find_existing(plan, name: str, kind: str | None, poi: dict | None):
    """已在册判定：poi_id 权威，其次同名 + 品类兼容。"""
    from app.services.agent import plan as plan_mod

    poi_id = str((poi or {}).get("source_poi_id") or "")
    if poi_id:
        for day in plan.days:
            for item in day.items:
                if isinstance(item, VisitItem) and item.poi_id == poi_id:
                    return item
    for day in plan.days:
        for item in day.items:
            if not isinstance(item, VisitItem):
                continue
            if plan_mod._name_dup(name, item.name) and _category_matches(item, kind):
                return item
    return None


async def try_fast_wish(agent, session, text: str):
    """单点加心愿的确定性回合；返回 (session, reply, None) 或 None（交主车道）。"""
    plan = getattr(session, "plan", None)
    if plan is None or getattr(session, "state", "") != "ready":
        return None
    if getattr(session, "pending_sites", None) or getattr(
        session, "pending_wish_cities", None
    ):
        return None
    name = parse_place_request(text)
    if name is None:
        return None
    poi, city = await _resolve_poi(agent, session, name)
    kind = _poi_kind(poi) if poi else None
    if kind == "other":
        logger.info(
            "plan: fast wish skipped %s (%s)", name, (poi or {}).get("category")
        )
        return None
    existing = _find_existing(plan, name, kind, poi)
    if existing is not None and existing.start_time is not None:
        reply = _already_reply(existing)
        session.history.append(ChatMessage(role="assistant", content=reply))
        _mark_fast_turn(session)
        return session, reply, None
    if existing is not None:
        # 已在册但没时刻（生成时被挤出窗口）：就地补位，同样不走 LLM。
        placement = _schedule_existing(
            plan, existing.item_id, city=(existing.city or "").strip()
        )
        if placement is None:
            return None
        if _hard_messages(placement.plan) - _hard_messages(plan):
            logger.info("plan: fast wish reschedule validation regressed for %s", name)
            return None
        poi = {
            "name": existing.name,
            "city": existing.city,
            "source_poi_id": existing.poi_id,
            "category": existing.category,
        }
        return await _commit(
            agent, session, text=text, name=name, poi=poi, placement=placement
        )
    if poi is None:
        return None
    poi = await _with_details(agent, poi)
    trip_cities = [c for c in (session.cities or []) if (c or "").strip()]
    if city and trip_cities and not any(_city_eq(city, c) for c in trip_cities):
        logger.info("plan: fast wish off-trip city %s for %s", city, name)
        return None
    if not city and trip_cities:
        city = trip_cities[0]
    before = _hard_messages(plan)
    if kind == "hotel":
        placement = place_hotel(plan, name=name, poi=poi)
    elif kind == "food":
        placement = place_food(
            agent,
            session,
            name=name,
            poi=poi,
            city=city,
            item_id=agent.alloc_item_id(plan),
        )
    else:
        placement = place_wish(
            plan,
            name=name,
            poi=poi,
            city=city,
            item_id=agent.alloc_item_id(plan),
        )
    if placement is None:
        return None
    if _hard_messages(placement.plan) - before:
        logger.info("plan: fast wish validation regressed for %s", name)
        return None
    return await _commit(
        agent, session, text=text, name=name, poi=poi, placement=placement
    )


async def _commit(
    agent, session, *, text: str, name: str, poi: dict, placement: WishPlacement
):
    """落定后收口：会话写回 + 必去/绑定 + 心愿行同步 + 回复入历史。"""
    session.plan = placement.plan
    if name not in session.must_visits:
        session.must_visits.append(name)
    bound = dict(poi)
    session.wish_bindings[name] = bound
    try:
        agent._wish_bindings[name] = bound
    except Exception:
        logger.warning("plan: fast wish binding cache failed", exc_info=True)
    reply = _placed_reply(placement)
    try:
        notes, _unresolved = await agent.sync_wishes_to_trip_items(
            session, [name], user_texts=[text]
        )
        if notes:
            reply += L(f"（{'；'.join(notes)}）", f" ({'; '.join(notes)})")
    except Exception:
        logger.warning("plan: fast wish trip-item sync failed", exc_info=True)
    for sync in ("_sync_wish_rows", "_sync_planned_rows"):
        try:
            getattr(agent, sync)(session)
        except Exception:
            logger.warning("plan: fast wish %s failed", sync, exc_info=True)
    logger.info(
        "plan: fast wish placed %s -> day %s %s (evicted=%s)",
        placement.item.name,
        placement.day,
        placement.item.start_time,
        [i.name for i in placement.removed],
    )
    session.history.append(ChatMessage(role="assistant", content=reply))
    _mark_fast_turn(session)
    return session, reply, None
