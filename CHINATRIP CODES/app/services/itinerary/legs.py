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
    return plan


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
    for after in timed[timed.index(last) + 1 :]:
        after_pt = _point(after)
        if after_pt is None:
            continue
        if haversine_km(last_pt, after_pt) > SAME_VENUE_KM:
            return  # 后面有真实下一站：正常腿链负责
    mode, terminal, service, _wait, _last = _access_profile(last)
    home = VisitItem(
        item_id="__city-terminal__",
        name="市区",
        city=last.city,
        day=day.day,
        duration_minutes=0,
        location=terminal,
    )
    br = access_breakdown(last, home)
    if br is None or br.get("direction") != "return":
        return
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
    detail = _access_return_detail(last, home, br)
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
        _attach_tail_return(day, timed)
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
        o["booking_url"] = _url(getattr(b, "booking_url", None) or o.get("ticket_url"))
        o["official_url"] = _url(
            o.get("official_url") or o.get("ticket_url") or getattr(b, "website", None)
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
