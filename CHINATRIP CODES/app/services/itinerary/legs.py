"""Intraday leg annotation (v2.4.3 §5 行程时间轴, product rule 2026-10-19).

annotate_legs() fills each VisitItem's display-only leg fields:
distance_to_next_km = straight-line (haversine) distance to the NEXT visit
of the same day, next_walk_minutes = walk estimate for that leg (×1.3
detour factor at 80 m/min), leg_source = "estimate". An intercity
TransferItem breaks the chain — the transfer card already describes that
leg. Pure function: no I/O, no LLM; idempotent, so it can run after every
plan mutation (solver output and LLM reranks never carry the fields).

leg_pairs() exposes the same chain to the agent's amap enrichment
(/v3/direction/walking — the nav module's engine, with POI-id snapping —
replaces the estimate with measured walking legs; leg_source flips to
"amap").
"""

from app.services.itinerary.fares import (
    access_fare_estimate,
    estimate_taxi_fare,
)
from app.services.itinerary.models import (
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.rules import (
    TAXI_WALK_MAX_KM,
    TRAVEL_MIN_PER_KM,
    access_breakdown,
    haversine_km,
    taxi_leg_min,
    travel_gap_needed,
)
from app.services.lang_ctx import L

DETOUR_FACTOR = 1.3  # straight-line -> walking-route correction
WALK_METERS_PER_MINUTE = 80.0  # ≈ 4.8 km/h sightseeing pace
MIN_LEG_KM = 0.05  # below this the two stops are effectively co-located


def _point(item: VisitItem) -> GeoPoint | None:
    """Leg math point: real POI coords, else a meal card's inherited anchor."""
    return item.location or item.anchor_location


# 占位卡随锚继承的接驳字段（2026-11-16「回城也是一样的接驳三段」）：
# 占位餐卡锚在班次点上时按该站的返程链算腿/隔隙——否则回城腿只剩
# 一条打车直线。幂等：每次 annotate 按当前锚重拷/清空。
_ACCESS_COPY_ATTRS = (
    "access_mode",
    "access_boarding",
    "access_service_minutes",
    "access_wait_minutes",
    "access_last_mile_minutes",
    "access_service_name",
    "access_depart_first",
    "access_depart_last",
    "access_ride_minutes",
    "access_return_last",
    "access_fare_text",
    "access_boarding_stop",
    "access_alight_stop",
    "access_operator",
    "access_depart_times",
    "access_return_times",
    "access_ticket_url",
    "access_official_url",
)


def resolve_meal_anchors(plan: ItineraryPlan) -> ItineraryPlan:
    """Re-anchor blank meal cards (午饭/晚饭自由安排) on the previous stop.


    2026-11-13 用户指令「BLANK LUNCH CARD 默认取上一站地址」：占位餐卡没有
    POI，卡面地址与「距下一站」腿都从当天前一落脚点继承。每次调用按当前
    顺序重算（幂等）——占位卡被拖到别处/其前面插入新条目，锚自动跟到新的
    前一站；跨城交通卡之后或当天首件没有可继承的落脚点则一律清空，绝不把
    出发城地址带过换乘卡。
    """
    for day in plan.days:
        last: VisitItem | None = None
        for item in day.items:
            if isinstance(item, TransferItem):
                last = None
                continue
            if item.anchor_from_prev:
                if last is not None and last.location is not None:
                    item.address = last.address
                    item.address_en = last.address_en
                    item.anchor_location = last.location
                    # 接驳档案随锚走：占位餐卡锚在班次点上时继承该站
                    # 的返程链字段（2026-11-16「回城三段」）；锚离开
                    # 班次点就清掉，幂等重算不残留。
                    for attr in _ACCESS_COPY_ATTRS:
                        setattr(item, attr, getattr(last, attr, None))
                else:
                    item.address = None
                    item.address_en = None
                    item.anchor_location = None
                    for attr in _ACCESS_COPY_ATTRS:
                        setattr(item, attr, None)
            if item.location is not None:
                last = item
    return plan


def leg_pairs(plan: ItineraryPlan) -> list[tuple[VisitItem, VisitItem, float]]:
    """Adjacent same-day visit pairs worth measuring, with straight-line km.

    Untimed cards break the chain (2026-11-03 Day4 show→park case): a leg
    into an unscheduled item is meaningless and rendered as an absurd
    night travel (a 949-minute leg from a 19:30 show to a forest park)."""
    out: list[tuple[VisitItem, VisitItem, float]] = []
    for day in plan.days:
        last: VisitItem | None = None
        for item in day.items:
            if isinstance(item, TransferItem) or item.start_time is None:
                last = None
                continue
            last_pt = _point(last) if last is not None else None
            cur_pt = _point(item)
            if last_pt is not None and cur_pt is not None:
                km = haversine_km(last_pt, cur_pt)
                if km >= MIN_LEG_KM:
                    out.append((last, item, km))
            last = item
    return out


def annotate_legs(plan: ItineraryPlan) -> ItineraryPlan:
    """Fill/clear the leg fields of every day in ``plan`` (in place)."""
    # 空餐卡先贴前一站（地址 + 锚点），腿链才能算出「餐 → 下一站」
    resolve_meal_anchors(plan)
    for day in plan.days:
        for item in day.items:
            if not isinstance(item, TransferItem):
                _clear_leg(item)
    for a, b, km in leg_pairs(plan):
        a.distance_to_next_km = round(km, 2)
        meters = km * 1000.0 * DETOUR_FACTOR
        a.next_walk_minutes = max(1, round(meters / WALK_METERS_PER_MINUTE))
        a.leg_source = "estimate"
        # 2026-11-16 用户拍板「网页正确显示时间和成本预估」：腿的时间用后端
        # 统一口径（含景区专线接驳链），成本按城市价目表估；前端只展示。
        city = a.city or b.city or ""
        br = access_breakdown(a, b)
        if br is not None:
            a.next_leg_mode = "access"
            a.next_leg_minutes = int(br["minutes"])
            a.next_leg_cost_cny = estimate_taxi_fare(
                city, float(br["taxi_km"])
            ) + access_fare_estimate(br["mode"])
            a.next_leg_cost_note = L(
                "含接驳票价估算", "includes an estimated shuttle fare"
            )
            a.next_leg_detail = (
                _access_return_detail(a, b, br)
                if br.get("direction") == "return"
                else _access_detail(a, b, br)
            )
        elif km <= TAXI_WALK_MAX_KM:
            a.next_leg_mode = "walk"
            a.next_leg_minutes = max(1, round(km * TRAVEL_MIN_PER_KM))
            a.next_leg_cost_cny = 0
        else:
            a.next_leg_mode = "taxi"
            need = travel_gap_needed(a, b)
            a.next_leg_minutes = int(need) if need is not None else taxi_leg_min(km)
            a.next_leg_cost_cny = estimate_taxi_fare(city, km)
    return plan


def _url(raw) -> str:
    """把库里的裸域名补成 https（EN 预订链接常没写 scheme）；空值回空串。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    return "https://" + text.lstrip("/")


def _clock(minutes) -> str | None:
    """570 → '09:30'；空值/越界回 None（前端只当补充信息）。"""
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return None
    if not (0 <= value < 24 * 60):
        return None
    return f"{value // 60:02d}:{value % 60:02d}"


def _access_detail(a: VisitItem, b: VisitItem, br: dict) -> dict:
    """接驳腿拆分（2026-11-16 用户拍板：网页要看清楚打车段/专线/步行/预约）。

    数据优先用卡上已挂的官方班次（w12_0039）；没有就现场查一次
    ``access_services``（读不到就只给打车+时长，不编 URL）。
    """
    svc = None
    if not getattr(b, "access_service_name", None):
        try:
            from app.services import access_services

            svc = access_services.fastest_service(
                b.city, b.name, arrive_boarding=9 * 60
            )
        except Exception:  # noqa: BLE001 - 班次库不可用不影响腿展示
            svc = None

    def _pick(attr: str, fallback=None):
        val = getattr(b, attr, None)
        if val not in (None, "", []):
            return val
        return getattr(svc, attr, None) if svc is not None else fallback

    details = {
        "mode": "access",
        "taxi_km": round(float(br.get("taxi_km") or 0.0), 2),
        "taxi_minutes": int(br.get("taxi_minutes") or 0),
        "wait_minutes": int(br.get("wait") or 0),
        "service_minutes": int(br.get("service") or 0),
        "walk_minutes": int(br.get("last") or 0),
        "gateway": _pick("access_boarding_stop") or "乘车点",
        "alight": _pick("access_alight_stop"),
        "service_name": _pick("access_service_name") or "",
        "operator": _pick("access_operator"),
        "departures": _pick("access_depart_times") or [],
        "returns": _pick("access_return_times") or [],
        "fare_text": _pick("access_fare_text"),
        "board_time": _clock(br.get("board")),
        "depart_time": _clock(br.get("depart")),
        "arrive_time": _clock(
            (br.get("depart") or 0)
            + int(br.get("service") or 0)
            + int(br.get("last") or 0)
            if br.get("depart") is not None
            else None
        ),
        "taxi_cost": estimate_taxi_fare(
            a.city or b.city, float(br.get("taxi_km") or 0.0)
        ),
        "access_cost": access_fare_estimate(br.get("mode")),
        # 购票优先用景点自己的预约入口（比线路页更贴近下单动作），
        # 官网用官方时刻表/说明页；两个都缺才留空，前端不出死链。
        "booking_url": _url(
            getattr(b, "booking_url", None) or _pick("access_ticket_url")
        ),
        "official_url": _url(
            _pick("access_official_url") or getattr(b, "website", None)
        ),
    }
    return details


def _access_return_detail(a: VisitItem, b: VisitItem, br: dict) -> dict:
    """回城腿拆分（2026-11-16 用户拍板「回城也是一样的接驳三段」）。

    段序与去程镜像：步行回乘车点 → 返程专线 → 市区落点打车到下一站；
    班次/票价/预约读 a 的返程档案（锚定占位餐卡已随锚继承），购票/官网
    仍优先景点自己的预约入口。
    """

    def _pick(attr: str, fallback=None):
        val = getattr(a, attr, None)
        if val not in (None, "", []):
            return val
        return fallback

    depart = br.get("depart")
    ride = int(br.get("service") or 0)
    return {
        "mode": "access",
        "direction": "return",
        "taxi_km": round(float(br.get("taxi_km") or 0.0), 2),
        "taxi_minutes": int(br.get("taxi_minutes") or 0),
        "wait_minutes": int(br.get("wait") or 0),
        "service_minutes": ride,
        "walk_minutes": int(br.get("last") or 0),
        "gateway": _pick("access_alight_stop") or "返程乘车点",
        "alight": _pick("access_boarding_stop"),
        "next_stop": b.name,
        "service_name": _pick("access_service_name") or "",
        "operator": _pick("access_operator"),
        "departures": _pick("access_return_times") or [],
        "returns": [],
        "fare_text": _pick("access_fare_text"),
        "board_time": _clock(br.get("board")),
        "depart_time": _clock(depart),
        "arrive_time": _clock(depart + ride if depart is not None else None),
        "taxi_cost": estimate_taxi_fare(
            a.city or b.city, float(br.get("taxi_km") or 0.0)
        ),
        "access_cost": access_fare_estimate(br.get("mode")),
        "booking_url": _url(
            getattr(a, "booking_url", None) or _pick("access_ticket_url")
        ),
        "official_url": _url(
            _pick("access_official_url") or getattr(a, "website", None)
        ),
    }


def _clear_leg(item: VisitItem) -> None:
    item.distance_to_next_km = None
    item.next_walk_minutes = None
    item.leg_source = None
    item.next_leg_minutes = None
    item.next_leg_mode = None
    item.next_leg_cost_cny = None
    item.next_leg_cost_note = None
    item.next_leg_detail = None
