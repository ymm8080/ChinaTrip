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

import json
from datetime import time as dt_time
from pathlib import Path

from app.services.itinerary.fares import (
    access_fare_estimate,
    estimate_taxi_fare,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.rules import (
    MORNING_RUSH_EXTRA_MINUTES,
    SAME_VENUE_KM,
    SCHEDULED_ACCESS_MODES,
    TAXI_WALK_MAX_KM,
    TRAVEL_MIN_PER_KM,
    _access_profile,
    _is_morning_hotel,
    access_breakdown,
    haversine_km,
    taxi_leg_min,
    travel_gap_needed,
)
from app.services.lang_ctx import L
from app.services.restaurants import is_dinner_placeholder

DETOUR_FACTOR = 1.3  # straight-line -> walking-route correction
WALK_METERS_PER_MINUTE = 80.0  # ≈ 4.8 km/h sightseeing pace
MIN_LEG_KM = 0.05  # below this the two stops are effectively co-located


def _point(item: VisitItem) -> GeoPoint | None:
    """Leg math point: real POI coords, else a meal card's inherited anchor."""
    return item.location or item.anchor_location


# 占位卡随锚继承的窗口字段（2026-11-16「回城也是一样的接驳三段」）：
# 卡上没有就按 (city, name) 查一次班次库（wish 快路径不经过 attach_access，
# 只靠 profile 档案算链，窗口字段得在这里补——否则专线行没有线名/落点）。
_ACCESS_WINDOW_ATTRS = (
    "access_service_name",
    "access_boarding_stop",
    "access_alight_stop",
    "access_operator",
    "access_depart_first",
    "access_depart_last",
    "access_ride_minutes",
    "access_return_last",
    "access_fare_text",
    "access_depart_times",
    "access_return_times",
    "access_ticket_url",
    "access_official_url",
)


def _service_window(item: VisitItem) -> dict:
    """班次点窗口字段：卡上有就原样；没有就按 (city, name) 查班次库。

    返回的键都是 VisitItem 上的 access_* 名，值可直接 setattr 回卡。
    """
    window = {attr: getattr(item, attr, None) for attr in _ACCESS_WINDOW_ATTRS}
    if window.get("access_service_name"):
        return window
    try:
        from app.services import access_services

        svc = access_services.fastest_service(
            getattr(item, "city", None), item.name, arrive_boarding=9 * 60
        )
    except Exception:  # noqa: BLE001 - 班次库不可用=不挂窗口
        svc = None
    if svc is None:
        return window
    return {
        "access_service_name": svc.service_name,
        "access_boarding_stop": svc.boarding_stop,
        "access_alight_stop": svc.alight_stop,
        "access_operator": svc.operator,
        "access_depart_first": svc.first_departure(),
        "access_depart_last": svc.last_departure(),
        "access_ride_minutes": svc.ride_minutes,
        "access_return_last": svc.return_last,
        "access_fare_text": svc.fare_text(),
        "access_depart_times": [
            f for m in svc.departures() if (f := access_services.fmt_minutes(m))
        ],
        "access_return_times": [
            f for m in svc.returns() if (f := access_services.fmt_minutes(m))
        ],
        "access_ticket_url": svc.ticket_url or svc.official_url,
        "access_official_url": svc.official_url or svc.ticket_url,
    }


def resolve_meal_anchors(plan: ItineraryPlan) -> ItineraryPlan:
    """Re-anchor blank meal cards (午饭/晚饭自由安排) on the previous stop.


    2026-11-13 用户指令「BLANK LUNCH CARD 默认取上一站地址」：占位餐卡没有
    POI，卡面地址与「距下一站」腿都从当天前一落脚点继承。每次调用按当前
    顺序重算（幂等）——占位卡被拖到别处/其前面插入新条目，锚自动跟到新的
    前一站；跨城交通卡之后或当天首件没有可继承的落脚点则一律清空，绝不把
    出发城地址带过换乘卡。

    2026-11-16 晚饭例外（用户拍板「当晚餐没有地址取下一个景点的地址，那就是
    酒店」）：占位晚饭若前站是远郊班次点、后站是市区落脚点（酒店），锚改取
    后站——景区散场后的晚饭跟着回城走，回城腿才从景区卡起算。
    """
    for day in plan.days:
        items = day.items
        for idx, item in enumerate(items):
            if not isinstance(item, VisitItem) or not item.anchor_from_prev:
                continue
            prev_loc: VisitItem | None = None
            for back in range(idx - 1, -1, -1):
                cand = items[back]
                if isinstance(cand, TransferItem):
                    break  # 换乘卡断锚：绝不把出发城地址带过换乘卡
                if cand.location is not None:
                    prev_loc = cand
                    break
            anchor = prev_loc
            next_loc: VisitItem | None = None
            for fwd in range(idx + 1, len(items)):
                cand = items[fwd]
                if isinstance(cand, TransferItem):
                    break
                if _point(cand) is not None:
                    next_loc = cand
                    break
            # 晚饭占位默认跟着「下一站」吃（2026-11-16 用户拍板「当晚餐没有
            # 地址取下一个景点的地址，那就是酒店」）：景区散场后的晚饭不留在
            # 景区——锚到下一站（酒店），回城腿才会从景区散场起算。
            if (
                str(item.item_id or "").startswith("food-dinner-ph")
                and prev_loc is not None
                and next_loc is not None
            ):
                mode_p, _tp, service_p, _wp, _lp = _access_profile(prev_loc)
                mode_n, _tn, service_n, _wn, _ln = _access_profile(next_loc)
                if (
                    mode_p in SCHEDULED_ACCESS_MODES
                    and service_p
                    and mode_n not in SCHEDULED_ACCESS_MODES
                ):
                    anchor = next_loc
            # 2026-11-16 上海朱家角案：远郊末站之后的晚饭不留在景区（打车回城
            # 再吃）——前站离城市锚点 ≥ TAIL_RETURN_MIN_KM、后面又没有真实下一站
            # 时清锚，别把 19:00 的晚饭写在景区停车场地址上。
            if (
                str(item.item_id or "").startswith("food-dinner-ph")
                and anchor is not None
                and anchor is prev_loc
                and next_loc is None
            ):
                _prev_pt = _point(anchor)
                _city_pt, _city_name = _day_city_anchor(day)
                if (
                    _prev_pt is not None
                    and _city_pt is not None
                    and haversine_km(_prev_pt, _city_pt) >= TAIL_RETURN_MIN_KM
                ):
                    anchor = None
            anchor_pt = _point(anchor) if anchor is not None else None
            if anchor is not None and anchor_pt is not None:
                item.address = anchor.address
                item.address_en = anchor.address_en
                item.anchor_location = anchor_pt
                # 接驳档案随锚走：占位餐卡锚在班次点上时继承该站的返程链
                # 字段（2026-11-16「回城三段」）；档案优先用规则层解析值
                # （卡上没有也能吃 profile）。
                mode, boarding, service, wait, last_mile = _access_profile(anchor)
                item.access_mode = mode
                item.access_boarding = boarding
                item.access_service_minutes = service or None
                item.access_wait_minutes = wait
                item.access_last_mile_minutes = last_mile
                for attr, val in _service_window(anchor).items():
                    setattr(item, attr, val)
            else:
                item.address = None
                item.address_en = None
                item.anchor_location = None
                item.access_mode = None
                item.access_boarding = None
                item.access_service_minutes = None
                item.access_wait_minutes = None
                item.access_last_mile_minutes = None
                for attr in _ACCESS_WINDOW_ATTRS:
                    setattr(item, attr, None)
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
            if cur_pt is None:
                # 无坐标卡（占位餐卡没锚）不吃链：腿直接连到再下一个带地址
                # 的卡（2026-11-16 用户口径「餐卡没地址就取再下个景点的地址」）
                continue
            if (
                getattr(item, "anchor_from_prev", False)
                and last_pt is not None
                and haversine_km(last_pt, cur_pt) <= SAME_VENUE_KM
            ):
                # 同址占位餐卡对腿透明：腿仍从前一个真实站点出发（朱家角 →
                # 静安寺，不是「午饭 → 静安寺」），2026-11-16 用户口径
                continue
            if last_pt is not None:
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
            _fare = br.get("fare_cny")
            a.next_leg_cost_cny = estimate_taxi_fare(city, float(br["taxi_km"])) + (
                float(_fare) if _fare is not None else access_fare_estimate(br["mode"])
            )
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
    _lift_return_over_placeholders(plan)
    _lift_legs_off_placeholders(plan)
    _attach_leg_returns(plan)
    _gate_item_links(plan)
    return plan


#: 回城段最低距离（2026-11-16 上海朱家角案）：当天最后一个真实站点离城市锚点
#: （酒店夜卡 / 晨卡 / 城心）超过这个距离、后面又只剩同址占位餐卡和没坐标的
#: 酒店卡时，就算没有班次档案（朱家角走地铁 17 号线或打车回）也要出一条
#: 「回城」——用户实报「从朱家角回去回程又没了」。
TAIL_RETURN_MIN_KM = 10.0
#: 上限：再远就不是同城日归（跨城由换乘卡负责，2026-11-16 脏坐标案）。
TAIL_RETURN_MAX_KM = 120.0


#: 酒店锚点离本城城心的最大合理距离：超过视为过期锚（跨城改点后晨卡还挂着
#: 上一座城的城心，2026-11-16 杭州天里上海锚案），改用城心。
CITY_ANCHOR_MAX_KM = 80.0


def _city_center(day: DayPlan) -> GeoPoint | None:
    city = str(day.base_city or "").removesuffix("市")
    try:
        from app.services.weather_open_meteo import CITY_COORDS

        xy = CITY_COORDS.get(city)
    except Exception:  # noqa: BLE001 — 城心表不可用=不出回城段
        xy = None
    if xy is None:
        return None
    return GeoPoint(lon=float(xy[1]), lat=float(xy[0]))


def _day_city_anchor(day: DayPlan) -> tuple[GeoPoint | None, str]:
    """回城段的目的地代理：酒店夜卡真坐标 → 晨卡锚点 → 城心（过期锚丢弃）。"""
    center = _city_center(day)

    def _sane(point: GeoPoint | None) -> bool:
        if point is None:
            return False
        return center is None or haversine_km(point, center) <= CITY_ANCHOR_MAX_KM

    morning: GeoPoint | None = None
    for item in day.items:
        if not isinstance(item, VisitItem):
            continue
        iid = str(item.item_id or "")
        if iid.startswith("hotel-night"):
            pt = _point(item)
            if _sane(pt):
                return pt, item.name or L("酒店", "hotel")
        elif iid.startswith("hotel-morning") and morning is None:
            pt = _point(item)
            if _sane(pt):
                morning = pt
    if morning is not None:
        return morning, L("市区", "city centre")
    if center is None:
        return None, ""
    return center, L("市区", "city centre")


def _lift_legs_off_placeholders(plan: ItineraryPlan) -> ItineraryPlan:
    """占位餐卡不背腿：同址占位卡上的腿挂回前一个真实站点（2026-11-16 朱家角案）。

    用户口径「朱家角回城是从朱家角的地址到下个卡地址（餐卡没地址就去再下个
    景点的地址）」：午饭/晚饭占位卡锚在景区上时，腿其实是从景区出发的；挂在
    餐卡上＝景区卡下面什么都没有，用户看不到回程。班次点（慕田峪）的三段
    回城链已由 :func:`_lift_return_over_placeholders` 处理，这里只搬剩下的
    打车腿（没有接驳档案的远郊点）。
    """

    def _move(src: VisitItem, dst: VisitItem) -> None:
        dst.distance_to_next_km = src.distance_to_next_km
        dst.next_walk_minutes = src.next_walk_minutes
        dst.leg_source = src.leg_source
        dst.next_leg_mode = src.next_leg_mode
        dst.next_leg_minutes = src.next_leg_minutes
        dst.next_leg_cost_cny = src.next_leg_cost_cny
        dst.next_leg_cost_note = src.next_leg_cost_note
        dst.next_leg_detail = src.next_leg_detail
        _clear_leg(src)

    for day in plan.days:
        items = day.items
        for idx, item in enumerate(items):
            if not isinstance(item, VisitItem) or not item.anchor_from_prev:
                continue
            if item.next_leg_minutes is None:
                continue
            item_pt = _point(item)
            if item_pt is None:
                continue
            site: VisitItem | None = None
            for back in range(idx - 1, -1, -1):
                cand = items[back]
                if isinstance(cand, TransferItem):
                    break  # 换乘卡断锚
                if not isinstance(cand, VisitItem):
                    continue
                if cand.anchor_from_prev or _is_morning_hotel(cand):
                    continue
                cand_pt = _point(cand)
                if cand_pt is None:
                    continue
                if haversine_km(cand_pt, item_pt) <= SAME_VENUE_KM:
                    site = cand
                break
            if site is None or site.next_leg_minutes is not None:
                continue
            _move(item, site)
    return plan


#: 让位档（2026-11-17 用户拍板）：60<d<90 → 1-15；90≤d<120 → 15-30；
#: d≥120 → 15 起、最多 60（「d>=120 -> above 30」）。
def _trim_band(dur: int) -> tuple[int, int]:
    if dur >= 120:
        return 15, 60
    if dur >= 90:
        return 15, 30
    if dur > 60:
        return 1, 15
    return 0, 0


def _next_start_after(day: DayPlan, site: VisitItem) -> int | None:
    """site **散场之后**第一张有时刻的卡的开始分钟（回城段要让路的那张）。

    必须从 site.end 起算：嵌在景点里的同址占位餐卡（anchor_from_prev，午饭
    11:30 站在 11:00-15:00 的景区卡上）不是「下一张卡」——按 site.start 找
    会把午饭当成下一站，回城段一算就「超时 270 分钟」，白缩 60 分钟。
    """
    s_min = _clock_minutes(site.start_time)
    end_min = _clock_minutes(site.end_time)
    if s_min is None:
        return None
    floor = end_min if end_min is not None else s_min
    best: int | None = None
    for item in day.items:
        if item is site or getattr(item, "anchor_from_prev", False):
            continue
        st = _clock_minutes(getattr(item, "start_time", None))
        if st is None or st < floor:
            continue
        if best is None or st < best:
            best = st
    return best


def _trim_site_for_return(plan: ItineraryPlan, day: DayPlan) -> None:
    """回城段压住下一张卡 → 缩短景点，绝不把回城/晚饭往后顶。

    2026-11-17 用户「SHRINK SITES' DURATION」「duration of 汽车 CAN BE
    REDUCED HALF HOUR OR MORE TO ADOPT THE NEXT CARD」：汽车乐园 240 分钟
    14:40-18:40 时回城段落到 18:30-19:27，压住 19:10 的晚饭——按档缩短
    景点让回城段落在下一张卡之前。
    """
    timed = [
        i for i in day.items if isinstance(i, VisitItem) and i.start_time is not None
    ]
    site = next(
        (
            i
            for i in reversed(timed)
            if (i.next_leg_detail or {}).get("direction") == "return"
        ),
        None,
    )
    if site is None:
        return
    detail = site.next_leg_detail or {}
    arrive = _parse_clock_text(detail.get("arrive_time"))
    if arrive is None:
        return
    nxt = _next_start_after(day, site)
    if nxt is None:
        return
    over = (_clock_minutes(arrive) or 0) - nxt
    if over <= 0:
        return
    # ① 先试「顺延下一张卡」（2026-11-17 用户「先看看 postpone 行不行」）：
    # 下一张是晚饭占位卡且顺延后仍 ≤19:30 开场 → 挪卡，景点时长不动。
    nxt_item = next(
        (
            i
            for i in day.items
            if i is not site and _clock_minutes(getattr(i, "start_time", None)) == nxt
        ),
        None,
    )
    # 只治「当天收尾」这一段（2026-11-17 用户口径）：下一张必须是晚饭占位卡
    # 或酒店卡，才是「回城段压住晚饭」的形状；后面还有真实景点时不动——
    # 那是普通腿链的事，硬缩景点会把白天行程改形（太平森林公园 180→120 案）。
    _tail_ok = nxt_item is not None and (
        is_dinner_placeholder(nxt_item)
        or str(getattr(nxt_item, "item_id", "") or "").startswith("hotel-night")
        or str(getattr(nxt_item, "category", "") or "") == "hotel"
    )
    if not _tail_ok:
        return
    if nxt_item is not None and is_dinner_placeholder(nxt_item):
        moved = _clock_minutes(arrive) or 0
        if moved <= 19 * 60 + 30:
            dur = int(nxt_item.duration_minutes or 90)
            nxt_item.start_time = _time_of(moved)
            nxt_item.end_time = _time_of(moved + dur)
            plan.assumptions.append(
                L(
                    f"晚饭为接上回城段顺延到 {nxt_item.start_time:%H:%M}",
                    f"Dinner moved to {nxt_item.start_time:%H:%M} "
                    "so the return leg fits",
                )
            )
            return
    lo, hi = _trim_band(int(site.duration_minutes or 0))
    cut = min(over, hi)
    if hi <= 0 or cut < lo:
        return
    end_min = (_clock_minutes(site.end_time) or 0) - cut
    start_min = _clock_minutes(site.start_time) or 0
    if end_min <= start_min:
        return
    before_dur = int(site.duration_minutes or 0)
    span = int(detail.get("service_minutes") or detail.get("taxi_minutes") or 0)
    new_end = end_min
    site.end_time = _time_of(new_end)
    site.duration_minutes = max(30, int(site.duration_minutes or 0) - cut)
    # 打车回城：发车=散场、到达=散场+车程，直接按新散场重写时刻（班次回城
    # 是时刻表铆钉，不在这里动）。
    if span and not detail.get("departures"):
        upd = dict(detail)
        upd["board_time"] = _clock(new_end)
        upd["depart_time"] = _clock(new_end)
        upd["arrive_time"] = _clock(new_end + span)
        site.next_leg_detail = upd
    plan.assumptions.append(
        L(
            f"「{site.name}」为接上回城段缩短 "
            f"{before_dur}→{site.duration_minutes} 分钟",
            f'"{site.name}" shortened {before_dur}→'
            f"{site.duration_minutes} min so the return leg fits",
        )
    )


def _attach_leg_returns(plan: ItineraryPlan) -> None:
    """当天收口：班次点三段回城链 + 远郊末站打车回城段（每天各一次）。"""
    for day in plan.days:
        timed = [
            item
            for item in day.items
            if isinstance(item, VisitItem) and item.start_time is not None
        ]
        _attach_tail_return(day, timed)
        _attach_plain_tail_return(day, timed)
        _trim_site_for_return(plan, day)


def _attach_plain_tail_return(day: DayPlan, timed: list[VisitItem]) -> None:
    """末站是远郊点、后面没有真实下一站：按打车口径补「回城」段（2026-11-16）。

    班次点（慕田峪那种专线）走 :func:`_attach_tail_return` 的接驳三段链；
    朱家角这类「地铁/打车去、打车回」的远郊点没有班次档案，旧逻辑一条腿都
    不出——景区卡下面空着，用户看不到任何回程。这里只管「当天最后一个真实
    站点 → 城市锚点」这一条：够远（≥ TAIL_RETURN_MIN_KM）、后面没有真下一站、
    自己也还没有腿时才挂；detail 标 ``direction=return`` + ``to_city``，出站
    装配会把它投影成独立的「回城」卡。
    """
    anchor_pt, anchor_name = _day_city_anchor(day)
    if anchor_pt is None:
        return
    last: VisitItem | None = None
    for item in timed:
        if getattr(item, "anchor_from_prev", False):
            continue  # 占位餐卡不是真实站点
        if _is_morning_hotel(item):
            continue
        if str(item.item_id or "").startswith("hotel-night"):
            continue
        if _point(item) is None:
            continue
        last = item
    if last is None or last.next_leg_minutes is not None:
        return
    last_pt = _point(last)
    if last_pt is None:
        return
    # 后面还有真实下一站（有坐标且不同址）：普通腿链负责，不重复出回城段
    for after in timed[timed.index(last) + 1 :]:
        after_pt = _point(after)
        if after_pt is None:
            continue
        if haversine_km(last_pt, after_pt) > SAME_VENUE_KM:
            return
    if last.city and day.base_city and last.city != day.base_city:
        return  # 跨城串号（上海天里塞杭州件）：换乘卡负责，不挂回城段
    km = haversine_km(last_pt, anchor_pt)
    if km < TAIL_RETURN_MIN_KM or km > TAIL_RETURN_MAX_KM:
        return
    start_min = _clock_minutes(last.end_time or last.start_time)
    minutes = taxi_leg_min(km)
    if minutes is None:
        return
    last.distance_to_next_km = round(km, 2)
    last.next_walk_minutes = max(
        1, round(km * 1000.0 * DETOUR_FACTOR / WALK_METERS_PER_MINUTE)
    )
    last.leg_source = "estimate"
    last.next_leg_mode = "taxi"
    last.next_leg_minutes = int(minutes)
    last.next_leg_cost_cny = estimate_taxi_fare(last.city or day.base_city, km)
    last.next_leg_cost_note = None
    last.next_leg_detail = {
        "mode": "taxi",
        "direction": "return",
        "to_city": True,
        "taxi_km": round(km, 2),
        "taxi_minutes": int(minutes),
        "taxi_rush_note": "",
        "wait_minutes": 0,
        "service_minutes": int(minutes),
        "walk_minutes": 0,
        "gateway": "",
        "alight": "",
        "next_stop": anchor_name,
        "service_name": "",
        "operator": None,
        "departures": [],
        "returns": [],
        "fare_text": None,
        "board_time": _clock(start_min),
        "next_item_id": None,
        "depart_time": _clock(start_min),
        "arrive_time": (
            _clock(start_min + int(minutes)) if start_min is not None else None
        ),
        "taxi_cost": estimate_taxi_fare(last.city or day.base_city, km),
        "access_cost": 0,
        "booking_url": None,
        "official_url": None,
    }


def _attach_tail_return(day: DayPlan, timed: list[VisitItem]) -> None:
    """当天最后一站是班次点：没有真实下一站时也出「回城段」（2026-11-16）。

    用户实报（行程 it-17867636：Day1 只有慕田峪；另一形状是午饭/晚饭都锚在
    景区、夜卡没坐标）：散场后怎么回城在卡上完全看不到。这里按返程链补
    「步行回乘车点 → 返程班 → 到市区落点」，detail 标 ``to_city``，前端腿行
    前缀「回城」。
    """
    if not timed:
        return
    last = None
    for item in reversed(timed):
        if getattr(item, "anchor_from_prev", False):
            continue  # 占位卡只是站在景区上，不是班次点
        mode_i, terminal_i, service_i, _w_i, _l_i = _access_profile(item)
        if mode_i in SCHEDULED_ACCESS_MODES and service_i and terminal_i is not None:
            last = item
            break
    if last is None or last.next_leg_minutes is not None:
        return
    last_pt = _point(last)
    if last_pt is None:
        return
    same_site = [last]
    for after in timed[timed.index(last) + 1 :]:
        after_pt = _point(after)
        if after_pt is None:
            continue
        if haversine_km(last_pt, after_pt) > SAME_VENUE_KM:
            return  # 后面有真实下一站：正常腿链负责
        same_site.append(after)
    mode, terminal, service, _wait, _last = _access_profile(last)
    home = VisitItem(
        item_id="__city-terminal__",
        name="市区",
        city=last.city,
        day=day.day,
        duration_minutes=0,
        location=terminal,
    )
    # board 基逐档试：景点散场 → 同址占位卡散场（午饭/晚饭），取「仍有返程
    # 班的最后一档」——晚饭 19 点在景区时不该拿 20:30 去赶 16:30 的末班。
    best: tuple[VisitItem, dict] | None = None
    fallback: tuple[VisitItem, dict] | None = None
    for base in same_site:
        proxy = last.model_copy(
            update={"start_time": base.start_time, "end_time": base.end_time}
        )
        br = access_breakdown(proxy, home)
        if br is None or br.get("direction") != "return":
            continue
        if fallback is None:
            fallback = (proxy, br)
        if br.get("depart") is None:
            continue
        best = (proxy, br)
    if best is None:
        best = fallback
    if best is None:
        return
    proxy, br = best
    km = haversine_km(last_pt, terminal)
    last.distance_to_next_km = round(km, 2)
    last.next_walk_minutes = max(
        1, round(km * 1000.0 * DETOUR_FACTOR / WALK_METERS_PER_MINUTE)
    )
    last.leg_source = "estimate"
    last.next_leg_mode = "access"
    last.next_leg_minutes = int(br["minutes"])
    _fare = br.get("fare_cny")
    _taxi_km = float(br["taxi_km"])
    last.next_leg_cost_cny = (
        estimate_taxi_fare(last.city, _taxi_km) if _taxi_km > 0.05 else 0
    ) + (float(_fare) if _fare is not None else access_fare_estimate(br["mode"]))
    last.next_leg_cost_note = L("含接驳票价估算", "includes an estimated shuttle fare")
    detail = _access_return_detail(proxy, home, br)
    detail["next_stop"] = detail.get("alight") or ""
    detail["to_city"] = True
    last.next_leg_detail = detail


def _lift_return_over_placeholders(plan: ItineraryPlan) -> ItineraryPlan:
    """回城腿挂回景区卡（2026-11-16 用户实报「NO BACK ARRANGEMENT」）。

    景区散场后紧跟着同址占位卡（午饭/晚饭锚在本站）时，腿对是 0 公里不成腿，
    回城链会挂在占位卡上或干脆没有。这里找「景区卡 → 第一个真实下一站」的
    返向链（board 按最后一张同址占位卡的散场时刻起算），明细挂回景区卡；占
    位卡上的同一段隐藏（同一段回城不重复显示）。幂等：annotate 每轮先清腿字
    段，本函数按当前布局重算。
    """
    for day in plan.days:
        timed = [
            item
            for item in day.items
            if isinstance(item, VisitItem) and item.start_time is not None
        ]
        for pos, a in enumerate(timed):
            if getattr(a, "anchor_from_prev", False):
                continue  # 占位卡不是回城起点：挂回真实景区卡
            if a.next_leg_minutes is not None:
                continue
            mode, _terminal, service, _wait, _last = _access_profile(a)
            if mode not in SCHEDULED_ACCESS_MODES or not service:
                continue
            a_pt = _point(a)
            if a_pt is None:
                continue
            board_item = a
            c: VisitItem | None = None
            for nxt in timed[pos + 1 :]:
                nxt_pt = _point(nxt)
                if nxt_pt is None:
                    continue
                if haversine_km(a_pt, nxt_pt) > SAME_VENUE_KM:
                    c = nxt
                    break
                board_item = nxt  # 同址占位卡：回城从它的散场时刻起算
            c_pt = _point(c) if c is not None else None
            if c is None or c_pt is None:
                continue
            proxy = a.model_copy(
                update={
                    "start_time": board_item.start_time,
                    "end_time": board_item.end_time,
                }
            )
            br = access_breakdown(proxy, c)
            if br is None or br.get("direction") != "return":
                continue
            km = haversine_km(a_pt, c_pt)
            a.distance_to_next_km = round(km, 2)
            a.next_walk_minutes = max(
                1, round(km * 1000.0 * DETOUR_FACTOR / WALK_METERS_PER_MINUTE)
            )
            a.leg_source = "estimate"
            a.next_leg_mode = "access"
            a.next_leg_minutes = int(br["minutes"])
            _fare = br.get("fare_cny")
            a.next_leg_cost_cny = estimate_taxi_fare(
                a.city or c.city, float(br["taxi_km"])
            ) + (
                float(_fare) if _fare is not None else access_fare_estimate(br["mode"])
            )
            a.next_leg_cost_note = L(
                "含接驳票价估算", "includes an estimated shuttle fare"
            )
            a.next_leg_detail = _access_return_detail(proxy, c, br)
            # 同址占位卡上的同一段隐藏（不重复显示）
            for item in timed[pos + 1 :]:
                if item is c:
                    break
                item.distance_to_next_km = None
                item.next_walk_minutes = None
                item.next_leg_mode = None
                item.next_leg_minutes = None
                item.next_leg_cost_cny = None
                item.next_leg_cost_note = None
                item.next_leg_detail = None
    return plan


RETURN_CARD_PREFIX = "access-return-"


def _clock_minutes(value) -> int | None:
    """time → 当天分钟数（None 透传）。"""
    if value is None:
        return None
    return value.hour * 60 + value.minute


def _time_of(minutes: int) -> dt_time:
    """当天分钟数 → time（夹在 00:00..23:59）。"""
    minutes = max(0, min(23 * 60 + 59, int(minutes)))
    return dt_time(minutes // 60, minutes % 60)


def _parse_clock_text(text) -> dt_time | None:
    """'14:30' → time；空值/坏值 None。"""
    if not text:
        return None
    try:
        hh, mm = str(text)[:5].split(":")
        return dt_time(int(hh), int(mm))
    except (TypeError, ValueError):
        return None


def _return_card_name(detail: dict) -> tuple[str, str]:
    service = (detail.get("service_name") or "").strip()
    service_en = (detail.get("service_name_en") or "").strip()
    if service:
        return (
            L(f"🚌 回城 · {service}", f"🚌 Return · {service_en or service}"),
            f"🚌 Return · {service_en or service}",
        )
    return (L("🚌 回城（打车回市区）", "🚌 Return to city (taxi)"), "")


def _return_hint_text(detail: dict) -> str:
    depart = detail.get("depart_time") or ""
    arrive = detail.get("arrive_time") or ""
    alight = detail.get("alight") or ""
    if not (depart or arrive):
        return ""
    zh = "🚌 回城" + (f" {depart}" if depart else "")
    en = "🚌 Return" + (f" {depart}" if depart else "")
    if arrive:
        zh += f" · 约 {arrive} 到 {alight}" if alight else f" · 约 {arrive}"
        en += f" · arrives {arrive}" + (f" at {alight}" if alight else "")
    elif alight:
        zh += f" · 到 {alight}"
        en += f" at {alight}"
    return L(zh, en)


def attach_return_cards(plan: ItineraryPlan) -> ItineraryPlan:
    """把回城段投影成一张独立卡（2026-11-16 用户拍板）。

    用户口径：①回城卡开始=游玩结束时间，有 SHUTTLE 就取最近的返程班次发车；
    ②回城卡落在午饭/晚饭同址占位卡之后——按时间排序（回城 14:30 晚于午饭
    14:08，不能排在午饭前面）。

    做法：读 ``annotate_legs`` 已经算好的返程链（景区卡 next_leg_detail,
    direction=return），在响应副本上生成 ``access-return-<景区卡>`` 卡：
    开始=班次发车（无时刻表用上一段结束），结束=到市区落点；插到「最后一张
    开始时间 ≤ 发车时刻」的条目之后；景区卡清腿、只留一行 ``return_hint``。
    ``detail.owner_item_id`` 指回景区卡，前端点班次仍按景区卡重排。

    只在 ``_plan_for_response`` 出站副本上调用——session/DB 不落卡，求解器、
    编辑链、心愿单同步都不受影响（幂等：每轮先按前缀摘掉旧卡）。
    """
    if plan is None:
        return plan
    out = plan.model_copy(deep=True)
    for day in out.days:
        day.items = [
            i for i in day.items if not (i.item_id or "").startswith(RETURN_CARD_PREFIX)
        ]
        site = None
        for item in day.items:
            if not isinstance(item, VisitItem):
                continue
            detail = item.next_leg_detail or {}
            if detail.get("direction") == "return":
                site = item
                break
        if site is None:
            continue
        detail = dict(site.next_leg_detail or {})
        start = _parse_clock_text(detail.get("depart_time"))
        if start is None:
            start = site.end_time
        if start is None:
            continue
        # 回城不得早于末站散场（2026-11-16 用户拍板「回城开始时间肯定是最后
        # 一个景点的结束时间」）：腿明细可能在上游补点/顺延之前算好，
        # depart_time 会落后于卡面 end_time（上海 D1 回城 16:00 vs 汽车乐园
        # 16:46 实拍）——出站投影时按卡面钳一次。
        site_end_min = _clock_minutes(site.end_time)
        start_min = _clock_minutes(start)
        clamped_return_start = False
        if site_end_min is not None and (start_min is None or start_min < site_end_min):
            start = _time_of(site_end_min)
            start_min = site_end_min
            clamped_return_start = True
        arrive = _parse_clock_text(detail.get("arrive_time"))
        if arrive is None or clamped_return_start:
            spent = detail.get("service_minutes")
            if spent is None:
                spent = site.next_leg_minutes or 0
            walk = int(detail.get("walk_minutes") or 0)
            arrive = _time_of((start_min or 0) + walk + int(spent))
        name, name_en = _return_card_name(detail)
        card = VisitItem(
            item_id=f"{RETURN_CARD_PREFIX}{site.item_id}",
            name=name,
            name_en=name_en or None,
            category="transfer",
            city=site.city,
            day=day.day,
            start_time=start,
            end_time=arrive,
            duration_minutes=max(
                0, (_clock_minutes(arrive) or 0) - (_clock_minutes(start) or 0)
            ),
            address=detail.get("gateway") or None,
            synthetic=True,
        )
        card_detail = dict(detail)
        card_detail["owner_item_id"] = site.item_id
        card_detail["to_city"] = True
        # 钳过的回城时刻同步回明细，前端腿行与卡片一致
        if clamped_return_start:
            card_detail["depart_time"] = _clock(start_min)
            card_detail["board_time"] = _clock(start_min)
            card_detail["arrive_time"] = _clock(_clock_minutes(arrive))
        card.next_leg_detail = card_detail
        hint = _return_hint_text(detail)
        # 明细留在景区卡上（下一轮装配还要用它重算回城卡，幂等）；
        # 摘要行清掉，前端按 return_hint 跳过这整段块（不重复显示）。
        site.return_hint = hint or None
        site.distance_to_next_km = None
        site.next_walk_minutes = None
        site.next_leg_mode = None
        site.next_leg_minutes = None
        site.next_leg_cost_cny = None
        site.next_leg_cost_note = None
        cut = 0
        for pos, item in enumerate(day.items):
            start_min = _clock_minutes(getattr(item, "start_time", None))
            if start_min is None:
                continue
            if start_min <= (_clock_minutes(start) or 0):
                cut = pos + 1
        day.items.insert(cut, card)
    return out


def _gate_item_links(plan: ItineraryPlan) -> None:
    """行程卡预约按钮的链接也过白名单闸（2026-11-16 用户拍板「链接先验证」）。

    卡面 🎫 预约按钮用的就是 VisitItem.booking_url，与腿行链接同源同风险
    （景山公园 bjgyol.com.cn 这类死链同样会从卡面出去）；幂等。
    """
    for day in plan.days:
        for item in day.items:
            if not isinstance(item, VisitItem):
                continue
            raw_value = getattr(item, "booking_url", None)
            if not raw_value:
                continue
            item.booking_url = _url(raw_value) or None


#: 规划页外链白名单（2026-11-16 用户拍板「post 出去的链接必须先验证」）。
#: 由 app/jobs/verify_access_links.py 实检生成；不在白名单 / verdict=dead 的
#: 链接一律不出——宁缺勿滥，不再把死链或没核实的页面贴到行程卡上。
_VERIFIED_LINKS_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "verified_links.json"
)
_LINK_CACHE: dict = {"mtime": None, "links": {}}


def _verified_links() -> dict:
    """读白名单（按 mtime 热更新；文件缺失=全部拒发，不出未验证链接）。"""
    try:
        mtime = _VERIFIED_LINKS_FILE.stat().st_mtime
    except OSError:
        return {}
    if _LINK_CACHE["mtime"] == mtime:
        return _LINK_CACHE["links"]
    links: dict = {}
    try:
        payload = json.loads(_VERIFIED_LINKS_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("links"), dict):
            links = payload["links"]
    except (OSError, ValueError):
        links = {}  # 白名单损坏=不出链（宁可没有链接，也不贴未验证页面）
    _LINK_CACHE["mtime"] = mtime
    _LINK_CACHE["links"] = links
    return links


def _url(raw) -> str:
    """库里的链接先归一成绝对地址，再按实检白名单放行（2026-11-16 用户拍板）。

    旧实现只补 https 就贴出去：八达岭「购票/预约」指向 ticket.badaling.cn，
    实测 TLS 握手失败 + http 404 = 死链。现在只发 app/data/verified_links.json
    里实检通过的（ok / ok_http_only / ok_retry / blocked_bot）；ok_http_only
    用 http 展示地址（站点本身不支持 TLS）。未在白名单=未验证，一并拒发。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "https://" + text.lstrip("/")
    # 双 scheme 候选：库里可能存 http（站点不支持 TLS），调用方也可能给裸域名
    links = _verified_links()
    matched = text
    entry = links.get(text)
    if not isinstance(entry, dict):
        alt = (
            "http://" + text[len("https://") :]
            if text.startswith("https://")
            else "https://" + text[len("http://") :]
        )
        entry = links.get(alt)
        if isinstance(entry, dict):
            matched = alt
    if not isinstance(entry, dict):
        return ""
    verdict = str(entry.get("verdict") or "").strip().lower()
    if verdict in ("", "dead", "unknown"):
        return ""
    display = str(entry.get("display_url") or "").strip()
    return display or matched


def _clock(minutes) -> str | None:
    """570 → '09:30'；空值/越界回 None（前端只当补充信息）。"""
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return None
    if not (0 <= value < 24 * 60):
        return None
    return f"{value // 60:02d}:{value % 60:02d}"


def _options_detail(
    a: VisitItem,
    b: VisitItem,
    br: dict,
    opts: list[dict],
    _from,
    city: str,
) -> dict:
    """多方式候选块明细：推荐项平铺为顶层字段（兼容旧读法），全量进 options。"""
    _rush = MORNING_RUSH_EXTRA_MINUTES if _is_morning_hotel(a) else 0
    for o in opts:
        if (
            o.get("boarding_lon") is not None
            and o.get("boarding_lat") is not None
            and _from is not None
        ):
            km = haversine_km(
                _from,
                GeoPoint(lon=float(o["boarding_lon"]), lat=float(o["boarding_lat"])),
            )
            o["taxi_km"] = round(km, 2)
            o["taxi_minutes"] = taxi_leg_min(km) + _rush
        else:
            o.setdefault("taxi_km", br.get("taxi_km"))
            o.setdefault("taxi_minutes", br.get("taxi_minutes"))
        o["taxi_cost"] = estimate_taxi_fare(city, float(o.get("taxi_km") or 0.0))
        _fare = o.get("fare_cny")
        o["access_cost"] = (
            float(_fare) if _fare is not None else access_fare_estimate(o.get("mode"))
        )
        # 购票优先景点自身预约入口（与旧口径一致），官网用班次行/景点官网
        o["booking_url"] = _url(getattr(b, "booking_url", None)) or _url(
            o.get("ticket_url")
        )
        o["official_url"] = (
            _url(o.get("official_url"))
            or _url(o.get("ticket_url"))
            or _url(getattr(b, "website", None))
        )
    rec = opts[0]
    return {
        "mode": "access",
        "taxi_km": round(float(br.get("taxi_km") or 0.0), 2),
        "taxi_minutes": int(br.get("taxi_minutes") or 0),
        "taxi_rush_note": (
            L("含早高峰 15′", "incl. 15' rush-hour traffic")
            if int(br.get("rush") or 0) > 0
            else ""
        ),
        "wait_minutes": int(rec.get("wait_minutes") or 0),
        "service_minutes": int(rec.get("ride_minutes") or 0),
        "walk_minutes": int(rec.get("last_mile_minutes") or 0),
        "gateway": rec.get("boarding_stop") or "乘车点",
        "alight": rec.get("alight_stop"),
        "service_name": rec.get("service_name") or "",
        "operator": rec.get("operator"),
        "departures": rec.get("departures") or [],
        "returns": rec.get("returns") or [],
        "fare_text": rec.get("fare_text"),
        "board_time": _clock(br.get("board")),
        # 下一站卡 id：去程卡上点「返程班次」时按它回推离场（2026-11-16）
        "next_item_id": getattr(b, "item_id", None),
        "depart_time": rec.get("depart"),
        "arrive_time": rec.get("arrive"),
        "taxi_cost": rec.get("taxi_cost"),
        "access_cost": rec.get("access_cost"),
        "booking_url": rec.get("booking_url"),
        "official_url": rec.get("official_url"),
        "options": opts,
    }


def _access_detail(a: VisitItem, b: VisitItem, br: dict) -> dict:
    """接驳腿拆分（2026-11-16 用户拍板：网页要看清楚打车段/专线/步行/预约）。

    数据优先用卡上已挂的官方班次（w12_0039）；没有就现场查一次
    ``access_services``（读不到就只给打车+时长，不编 URL）。
    2026-11-16 二拍：同站有接驳车/火车等多种方式时，``options`` 出
    多个候选块（换乘少+时间短者 recommended），乘车点按方式各显清晰站名。
    """
    _from = a.location or getattr(a, "anchor_location", None)
    city = a.city or b.city or ""
    opts = [
        dict(o)
        for o in (br.get("options") or [])
        if isinstance(o, dict) and o.get("service_name")
    ]
    if opts:
        return _options_detail(a, b, br, opts, _from, city)

    window = _service_window(b)

    def _pick(attr: str, fallback=None):
        val = getattr(b, attr, None)
        if val not in (None, "", []):
            return val
        got = window.get(attr)
        return got if got not in (None, "", []) else fallback

    details = {
        "mode": "access",
        "taxi_km": round(float(br.get("taxi_km") or 0.0), 2),
        "taxi_minutes": int(br.get("taxi_minutes") or 0),
        "taxi_rush_note": (
            L("含早高峰 15′", "incl. 15' rush-hour traffic")
            if int(br.get("rush") or 0) > 0
            else ""
        ),
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
        # 下一站卡 id：去程卡上点「返程班次」时按它回推离场（2026-11-16）
        "next_item_id": getattr(b, "item_id", None),
        "depart_time": _clock(br.get("depart")),
        "arrive_time": _clock(
            (br.get("depart") or 0)
            + int(br.get("service") or 0)
            + int(br.get("last") or 0)
            if br.get("depart") is not None
            else None
        ),
        "taxi_cost": (
            estimate_taxi_fare(a.city or b.city, float(br.get("taxi_km") or 0.0))
            if float(br.get("taxi_km") or 0.0) > 0.05
            else 0
        ),
        "access_cost": access_fare_estimate(br.get("mode")),
        # 购票优先用景点自己的预约入口（比线路页更贴近下单动作），
        # 官网用官方时刻表/说明页；两个都缺才留空，前端不出死链。
        "booking_url": _url(getattr(b, "booking_url", None))
        or _url(_pick("access_ticket_url")),
        "official_url": _url(_pick("access_official_url"))
        or _url(getattr(b, "website", None)),
    }
    return details


def _access_return_detail(a: VisitItem, b: VisitItem, br: dict) -> dict:
    """回城腿拆分（2026-11-16 用户拍板「回城也是一样的接驳三段」）。

    段序与去程镜像：步行回乘车点 → 返程专线 → 市区落点打车到下一站；
    班次/票价/预约读 a 的返程档案（锚定占位餐卡已随锚继承），购票/官网
    仍优先景点自己的预约入口。
    """

    window = _service_window(a)

    def _pick(attr: str, fallback=None):
        val = getattr(a, attr, None)
        if val not in (None, "", []):
            return val
        got = window.get(attr)
        return got if got not in (None, "", []) else fallback

    depart = br.get("depart")
    ride = int(br.get("service") or 0)
    return {
        "mode": "access",
        "direction": "return",
        "taxi_km": round(float(br.get("taxi_km") or 0.0), 2),
        "taxi_minutes": int(br.get("taxi_minutes") or 0),
        "taxi_rush_note": (
            L("含早高峰 15′", "incl. 15' rush-hour traffic")
            if int(br.get("rush") or 0) > 0
            else ""
        ),
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
        # 下一站卡 id：去程卡上点「返程班次」时按它回推离场（2026-11-16）
        "next_item_id": getattr(b, "item_id", None),
        "depart_time": _clock(depart),
        "arrive_time": _clock(depart + ride if depart is not None else None),
        "taxi_cost": estimate_taxi_fare(
            a.city or b.city, float(br.get("taxi_km") or 0.0)
        ),
        "access_cost": access_fare_estimate(br.get("mode")),
        "booking_url": _url(getattr(a, "booking_url", None))
        or _url(_pick("access_ticket_url")),
        "official_url": _url(_pick("access_official_url"))
        or _url(getattr(a, "website", None)),
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
