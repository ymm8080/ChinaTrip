"""F-30 materialise_plan: Solution -> ItineraryPlan.

Cards start/end come from solution intervals; access-leg fields and the
independent outbound/return cards come from the *same* F-14 intervals the model
constrained (card == leg by construction — the legacy
``attach_return_cards`` reads annotate_legs' display chain instead, so
assembly synthesises the transfer cards from the authoritative solution
intervals directly). A requested item not present becomes an
``unplaced`` entry with reason codes + bilingual reason; an untimed
requested card cannot exist by type (SolutionItem always carries
minutes).
"""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING, Optional

from ...itinerary.item_ids import ensure_unique_item_ids
from ...itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    UnplacedCandidate,
    VisitItem,
)
from ...itinerary.rules import SHUTTLE_BOARD_BUFFER_MINUTES, TAXI_HAIL_MINUTES
from ...itinerary.stay_city import apply_stay_cities
from ..model.c05_c08 import DEFAULT_GATEWAY_TAXI_MINUTES
from ..snapshot import snapshot_hash

if TYPE_CHECKING:  # pragma: no cover
    from ..types import FactSnapshot, Solution

RETURN_CARD_PREFIX = "access-return-"
OUTBOUND_CARD_PREFIX = "access-out-"
RETURN_HINT = {
    "zh": "游玩结束后按返程班次回城（独立回城卡）",
    "en": "Return shuttle after the visit (separate return card)",
}


def _hhmm(minutes: int) -> time:
    return time(minutes // 60 % 24, minutes % 60)


def _base_city(snapshot: "FactSnapshot", day: int) -> str:
    cities = list(snapshot.request.cities) or ["?"]
    if len(cities) == 1:
        return cities[0]
    return cities[min(day - 1, len(cities) - 1)]


def _is_closed_trip(snapshot: "FactSnapshot") -> bool:
    cities = [c for c in (snapshot.request.cities or ()) if c]
    if len(cities) < 2:
        return False

    def _n(c: str) -> str:
        return str(c or "").strip().removesuffix("市")

    return _n(cities[0]) == _n(cities[-1])


def _day_label(items, snapshot: "FactSnapshot", day: int) -> str:
    """R13o②：天的 base_city 按当天实际在排的卡取多数城——此前按
    请求城市序做朴素索引映射（day2=城市2），自由分配/显式分城窗下标签
    与内容错位（R13n 跨城探针：Day2/Day3 标「西安」但装的全是北京
    景点）。空日回落分城日窗（C-17 同口径），再退旧索引兜底。

    2026-11-22 闭合行程末日修正：末日晨/夜酒店卡的城市是 _base_city
    朴素索引（closed 时=出发城）——轻日多数标签被合成酒店卡劫走，末日
    被误标成出发城（返程腿语义/夜卡城市全错）。末日剔除 hotel 卡再取
    多数（游玩卡说了算）；闭合尾城真实停留窗下多数仍是尾城，口径自洽。
    """
    _closed_last = (
        _is_closed_trip(snapshot) and day == int(snapshot.request.days or 0)
    )
    counts: dict[str, int] = {}
    for it in items:
        if _closed_last and str(getattr(it, "category", "") or "") == "hotel":
            continue
        city = getattr(it, "city", None)
        if city:
            counts[str(city)] = counts.get(str(city), 0) + 1
    if counts:
        return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    try:
        from ..model.c17_city_days import city_day_windows

        windows = city_day_windows(
            snapshot.request.cities,
            snapshot.request.days,
            dict(snapshot.request.city_days or {}),
            origin_days=getattr(snapshot.request, "origin_days", 0) or 0,
        )
        for city, win in windows.items():
            if win[0] <= day <= win[1]:
                return city
    except Exception:  # noqa: BLE001 - 窗口推导失败退旧口径
        pass
    return _base_city(snapshot, day)


def _location(cand) -> Optional[GeoPoint]:
    if cand.lon is None or cand.lat is None:
        return None
    return GeoPoint(lon=float(cand.lon), lat=float(cand.lat))


def compact_days(plan, snapshot):
    """R2 deterministic day compaction (timing-only, barrier-aware).

    Movable cards pull left inside their windows; FIXED cards -- system
    meals, shuttle/return cards, user pins -- act as immovable barriers
    the pass must not overlap; inter-card gaps use the audit formula
    max(30, taxi(km)). Placement/order/durations never change.
    """
    from datetime import time as _time

    from ..inputs.hours_caps import parse_first_window
    from ..inputs.travel import haversine_km

    def _taxi_gap(a_item, b_item):
        # R13o①：城际腿卡（TransferItem）无坐标字段——getattr 口径，
        # 前件是城际腿时按 30 分钟接驳地板。
        la = getattr(a_item, "location", None)
        lb = getattr(b_item, "location", None)
        if la is None or lb is None:
            return 30
        km = haversine_km(la.lon, la.lat, lb.lon, lb.lat)
        ride = min(180, round(km * 1.3 / 35.0 * 60))
        return max(30, ride + 30)

    def _m(item):
        return item.start_time.hour * 60 + item.start_time.minute

    def _set(item, target, dur):
        end = target + dur
        item.start_time = _time(target // 60 % 24, target % 60)
        item.end_time = _time(end // 60 % 24, end % 60)

    cand_by_poi = {c.poi_id: c for c in snapshot.candidates if c.poi_id}
    # R9-1：day1_start 地板（C-04 同源解析）——压实起点不得早于用户
    # 指定的首日出发时刻（brief「LEAVE HOTEL ON 11AM」），否则拉左会把
    # 合规解压回 08:30/开窗早档
    day1_floor = None
    _d1 = getattr(getattr(snapshot, "request", None), "day1_start", None)
    if _d1:
        try:
            _hh, _mm = str(_d1).split(":")
            day1_floor = int(_hh) * 60 + int(_mm)
        except ValueError:
            day1_floor = None
    _arr_day = getattr(getattr(snapshot, "request", None), "arrival_day", None)
    _dep_day = getattr(getattr(snapshot, "request", None), "departure_day", None)
    arrival_day_floor = (None, 0)
    departure_day_cap: dict = {}
    if _arr_day:
        from ..model.c05_c08 import _hhmm as _c05_hhmm
        from ..model.c05_c08 import arrival_floor_for

        _at = _c05_hhmm(getattr(snapshot.request, "arrival_time", None))
        if _at is not None:
            arrival_day_floor = (
                int(_arr_day),
                _at
                + arrival_floor_for(getattr(snapshot.request, "arrival_mode", None)),
            )
    if _dep_day:
        from ..model.c05_c08 import _hhmm as _c05_hhmm
        from ..model.c05_c08 import arrival_floor_for

        _dt2 = _c05_hhmm(getattr(snapshot.request, "departure_time", None))
        if _dt2 is not None:
            departure_day_cap[int(_dep_day)] = _dt2 - arrival_floor_for(
                getattr(snapshot.request, "departure_mode", None)
            )
    for day in plan.days:
        timed = [i for i in day.items if i.start_time is not None]
        fixed = [
            i
            for i in timed
            # R13o①：城际腿卡（TransferItem）=固定屏障（无 category 字段，
            # 此前 (i.category or "") 直接 AttributeError——只在带城际卡的
            # 引擎计划上炸）。
            if not isinstance(i, VisitItem)
            or getattr(i, "synthetic", False)
            or (i.category or "") in ("transfer", "transport", "food")
            or getattr(i, "access_mode", None)
            or getattr(i, "pinned", False)
        ]
        movable = [
            i for i in timed if i not in fixed and not getattr(i, "pinned", False)
        ]
        if not movable:
            continue
        # R12-M2 排序雷修复（2026-11-19）：元组第三位是 VisitItem——平手
        # 时 Python 比较卡对象直接 TypeError（双卡同时刻即崩，R12 中间态
        # 双渲染实测触发过）。key 只比前两位，平手保原序（sorted 稳定）。
        barriers = sorted(
            [(_m(f), _m(f) + int(f.duration_minutes or 60), f) for f in fixed],
            key=lambda b: (b[0], b[1]),
        )

        def _earliest(card, after_min, prev_card):
            cand = cand_by_poi.get(card.poi_id)
            window = parse_first_window(cand.opening_hours if cand else None)
            lo = window[0] if window else after_min
            target = max(lo, after_min)
            dur = int(card.duration_minutes or 60)
            # nudge right past any overlapping barrier
            for _ in range(len(barriers) + 1):
                clash = next(
                    (b for b in barriers if target < b[1] and target + dur > b[0]),
                    None,
                )
                if clash is None:
                    return target
                target = clash[1] + (30 if (card.category or "") != "food" else 0)
            return target

        prev = None
        prev_end = 8 * 60 + 30
        if day.day == 1 and day1_floor:
            prev_end = max(prev_end, day1_floor)
        # R9-2：中途转移日——到达日地板（到达时刻+模式缓冲）/离开日顶盖
        # （C-05 同源），压实拉左不得越过
        if day.day == arrival_day_floor[0]:
            prev_end = max(prev_end, arrival_day_floor[1])
        dep_cap = departure_day_cap.get(day.day)
        for card in sorted(timed, key=_m):
            if card in movable:
                gap = _taxi_gap(prev, card) if prev is not None else 0
                target = _earliest(card, prev_end + gap if prev else prev_end, prev)
                if dep_cap is not None:
                    dur = int(card.duration_minutes or 60)
                    target = min(target, max(8 * 60 + 30, dep_cap - dur))
                if target < _m(card):
                    _set(card, target, int(card.duration_minutes or 60))
            prev = card
            prev_end = max(prev_end, _m(card) + int(card.duration_minutes or 60))
    return plan


def push_after_intercity(plan: ItineraryPlan) -> ItineraryPlan:
    """R13o①：城际腿屏障日的右推级联——compact_days 只向左压实不推右，
    而城际卡是装配期新增屏障（引擎解不知道它），腿到时刻前开工的卡要
    顺次右推保序。钉住卡（铁律 19）不推；推完游标连续（30 分钟接驳地板）。
    幂等：卡已在腿后即零位移。"""
    from datetime import time as _time

    def _m(item):
        return item.start_time.hour * 60 + item.start_time.minute

    for day in plan.days:
        if not day.items:
            continue
        # 晨卡可与腿同刻（attach_meal_cards 按 start+id 排序可能把
        # hotel-morning 排在 xfer 前）——扫首个城际腿，不认 items[0]。
        xfer = next(
            (
                i
                for i in day.items
                if isinstance(i, TransferItem)
                and str(i.item_id or "").startswith("xfer-")
            ),
            None,
        )
        if xfer is None:
            continue
        # 2026-11-22 返程腿（傍晚出发）不右推：右推级联是去程腿语义
        # （卡推到「到达之后」）；返程腿是「白天游玩 + 傍晚回城」——
        # 把全天卡推到 19:30 之后 = 返程日全灭（闭合返程顶盖 C-05 已
        # 保证模型卡在腿前收尾，无需推）。
        if _m(xfer) >= 12 * 60:
            continue
        arrive = _m(xfer) + int(xfer.duration_minutes or 120)
        cursor = arrive + 30
        for card in day.items:
            if card is xfer:
                continue
            if not isinstance(card, VisitItem) or card.start_time is None:
                continue
            if getattr(card, "pinned", False):
                cursor = max(cursor, _m(card) + int(card.duration_minutes or 60))
                continue
            cur = _m(card)
            dur = int(card.duration_minutes or 60)
            if cur < cursor:
                shift = cursor - cur
                new_start = cur + shift
                card.start_time = _time(new_start // 60 % 24, new_start % 60)
                card.end_time = _time(
                    (new_start + dur) // 60 % 24, (new_start + dur) % 60
                )
                cur = new_start
            cursor = max(cursor, cur + dur)
    return plan


def _apply_flag_anchors(days, snapshot: "FactSnapshot") -> None:
    """R18（2026-11-22 用户令「不可能没有升旗时间」）：升旗时刻装配期落硬锚。

    天安门广场（best_visit_time=sunrise）卡的起止由 C-01 等式钉在
    flag_schedule 真值上，但此前**不写 fixed_sessions**——下游所有「升旗锚
    保护」都不认这张卡：摘钉重排（agent/plan.py）、晨卡拉回、重叠推平、
    coverage 自愈全按普通卡处理，卡一挪旗时就没了（legacy 路一直带 fixed，
    所以只有引擎路丢）。这里把同一份真值落成 fixed_sessions，让两道保护
    重新生效：模型侧等式（定时刻）+ 卡上锚（保时刻）。

    只打标不改时刻：时刻归模型管（等式已保证等于真值），装配期再改会让
    已按原时刻排好的后继卡违反转场间隔。幂等；无出发日期/库空 → 不动作。
    """
    from ...flag_schedule import flag_minutes_by_day

    minutes = flag_minutes_by_day(
        getattr(snapshot.request, "start_date", None),
        getattr(snapshot.request, "days", 0),
    )
    if not minutes:
        return
    for day in days:
        flag_min = minutes.get(day.day)
        if not flag_min:
            continue
        anchor = time(flag_min // 60 % 24, flag_min % 60)
        for item in day.items:
            if not isinstance(item, VisitItem):
                continue
            if str(getattr(item, "best_visit_time", "") or "") != "sunrise":
                continue
            if item.fixed_sessions == [anchor]:
                continue
            item.fixed_sessions = [anchor]


def materialize_plan(
    solution: "Solution",
    snapshot: "FactSnapshot",
    *,
    itinerary_id: Optional[str] = None,
) -> ItineraryPlan:
    """Base cards + access fields + outbound/return cards + unplaced (F-30)."""
    cand_by_cid = {c.cid: c for c in snapshot.candidates}
    legs_by_cid_day = {
        (leg.get("cid"), leg.get("day")): leg for leg in solution.access_legs
    }
    days = []
    seq = 0

    def next_id() -> str:
        nonlocal seq
        seq += 1
        return "v%d" % seq

    # R8-S2b 餐类必去：真餐厅已顶餐卡（命名卡）——访视渲染去重
    bound_render = {
        (m.get("bound_cid"), int(m.get("day") or 0))
        for m in getattr(solution, "meal_anchors", ()) or ()
        if m.get("bound_cid")
    }
    for day_no in range(1, snapshot.request.days + 1):
        items: list[VisitItem] = []
        day_outbounds: list[tuple[int, int]] = []
        day_items = [it for it in solution.items if it.day == day_no]
        day_items.sort(key=lambda it: (it.start_min, it.cid))
        for sol_item in day_items:
            cand = cand_by_cid.get(sol_item.cid)
            if cand is None:
                continue
            if (sol_item.cid, day_no) in bound_render:
                continue
            leg = legs_by_cid_day.get((sol_item.cid, day_no))
            card = VisitItem(
                item_id=next_id(),
                name=cand.name,
                poi_id=cand.poi_id,
                category=cand.category,
                city=cand.city or _base_city(snapshot, day_no),
                location=_location(cand),
                opening_hours=cand.opening_hours,
                day=day_no,
                start_time=_hhmm(sol_item.start_min),
                end_time=_hhmm(sol_item.end_min),
                duration_minutes=sol_item.end_min - sol_item.start_min,
                pinned=bool(sol_item.pinned),  # F-20/F-51: 铁律 19 豁免面
                # R12-F（2026-11-19 用户令「查有多少应该起作用但没起
                # 作用的」）：引擎必去卡打 must 标——legacy 全链判定
                # （hotfix 让位/降级/铁律 19/占位识别）此前对引擎卡
                # 全盲（live 实锤：天坛被剥成想去而景山不让位）。
                must=(cand.kind == "requested"),
                synthetic=False,
                # R6: 打分器/审计的大点豁免与免检口径需要与模型同源——
                # tier 与 best_visit_time 必须随卡（此前只给了 unplaced 行）
                tier=getattr(cand, "tier", None),
                best_visit_time=getattr(cand, "best_visit_time", None),
            )
            # R13o④（R13n 审计「切换后失效了」）：预约提示/购票链接随卡
            # ——legacy 卡从 poi 行带 reservation_hint/booking_url/website，
            # 引擎卡此前全缺=前端所有观光卡显示「预约信息无」。字段随
            # 候选（live 缝盖，含别名兜底的全列行）。
            card.reservation_hint = getattr(cand, "reservation_hint", None)
            card.booking_url = getattr(cand, "booking_url", None)
            card.website = getattr(cand, "website", None)
            if leg is not None:
                # card == leg: the same F-14 interval the model constrained.
                profile = next(
                    (
                        p
                        for p in snapshot.access_profiles
                        if p.to_poi in (cand.poi_id, cand.cid)
                    ),
                    None,
                )
                if profile is not None:  # F-30 fare/service attach
                    card.access_fare_text = profile.fare_text
                    card.access_service_name = profile.service_name or profile.operator
                    # R13m：真实 mode + 班次窗口盖卡（legacy
                    # poi_access.attach_access 同口径）——access_mode 此前
                    # 恒为字面量 "access"，rules._access_profile 的
                    # SCHEDULED_ACCESS_MODES 门不认 → access_breakdown 恒
                    # None → 引擎计划班次块/回城三段/班次 chips 全不渲染、
                    # 点选返程 422 no_return_leg。display 链从卡上字段点亮。
                    card.access_mode = profile.mode or "shuttle"
                    card.access_operator = profile.operator
                    card.access_boarding_stop = profile.gateway
                    card.access_ride_minutes = int(profile.ride_minutes)
                    card.access_last_mile_minutes = int(profile.last_mile_minutes or 0)
                    card.access_wait_minutes = int(profile.wait_minutes or 0)
                    card.access_depart_times = list(profile.departures)
                    card.access_return_times = list(profile.returns)
                    card.access_ticket_url = profile.ticket_url
                    card.access_official_url = profile.official_url
                    # R15：打车段分钟随卡（档案值，缺省网关打车口径）——
                    # 晨卡离店=班次−打车与去程打车卡共用同源分钟数。
                    card.access_taxi_minutes = (
                        int(getattr(profile, "taxi_minutes", 0) or 0)
                        or DEFAULT_GATEWAY_TAXI_MINUTES
                    )
                    if (
                        profile.boarding_lon is not None
                        and profile.boarding_lat is not None
                    ):
                        card.access_boarding = GeoPoint(
                            lon=float(profile.boarding_lon),
                            lat=float(profile.boarding_lat),
                        )
                else:
                    card.access_mode = "access"
                card.access_service_minutes = leg.get("arrive_poi_min", 0) - leg.get(
                    "depart_min", 0
                )
                card.return_hint = RETURN_HINT["zh"]
                # R13-#3 去程接驳卡（回城卡的镜像，同一 F-14 区间）：市区
                # 乘车点→远郊景点的班次段独立成卡，插在访问卡之前。synthetic
                # transfer + access_mode → compact_days 固定屏障；卡不带坐标
                # → leg_pairs 透明，前站→远郊点的接驳详情链不受影响。
                depart = leg.get("depart_min")
                arrive_poi = leg.get("arrive_poi_min")
                if depart is not None and arrive_poi is not None:
                    gateway = str(leg.get("gateway") or "")
                    ride = int(arrive_poi) - int(depart)
                    if gateway:
                        name = "🚌 去程 · %s → 班车约%d分" % (gateway, ride)
                        name_en = "🚌 Outbound · shuttle from %s (~%d min)" % (
                            gateway,
                            ride,
                        )
                    else:
                        name = "🚌 去程 · 班车约%d分" % ride
                        name_en = "🚌 Outbound shuttle (~%d min)" % ride
                    out = VisitItem(
                        item_id="%s%s" % (OUTBOUND_CARD_PREFIX, card.item_id),
                        name=name,
                        name_en=name_en,
                        category="transfer",
                        city=_base_city(snapshot, day_no),
                        day=day_no,
                        start_time=_hhmm(int(depart)),
                        end_time=_hhmm(int(arrive_poi)),
                        duration_minutes=ride,
                        synthetic=True,
                        access_mode="access",
                        address=gateway or None,
                    )
                    items.append(out)
                    # R15：记下当天去程班次与打车分钟（晨卡离店=班次−打车同源）
                    day_outbounds.append(
                        (
                            int(depart),
                            int(getattr(card, "access_taxi_minutes", 0) or 0)
                            or DEFAULT_GATEWAY_TAXI_MINUTES,
                        )
                    )
            items.append(card)
            if leg is not None and leg.get("return_depart_min") is not None:
                arrive_city = leg.get("arrive_city_min")
                ret = VisitItem(
                    item_id="%s%s" % (RETURN_CARD_PREFIX, card.item_id),
                    name="回城",
                    name_en="Return to city",
                    category="transfer",
                    city=_base_city(snapshot, day_no),
                    day=day_no,
                    start_time=_hhmm(int(leg["return_depart_min"])),
                    end_time=(
                        _hhmm(int(arrive_city)) if arrive_city is not None else None
                    ),
                    duration_minutes=(
                        int(arrive_city) - int(leg["return_depart_min"])
                        if arrive_city is not None
                        else None
                    ),
                    synthetic=True,
                )
                items.append(ret)
        # R13o⑤⑥（R13n 审计）：C-13 酒店锚物化——求解器每天早就算好
        # morning/night 酒店窗（c09 hotel_vars），extract_hotel_anchors 已
        # 带出 solution.hotel_anchors，materialize 此前直接丢弃=引擎计划
        # 零晨卡/零夜卡（2026-11-16 拍板「早晨卡只有出发时间」在响应层
        # _morning_point_cards 收点生效）。
        label = _day_label(items, snapshot, day_no)
        hotel_by_slot = {
            str(h.get("slot")): h
            for h in getattr(solution, "hotel_anchors", ()) or ()
            if int(h.get("day") or 0) == day_no
        }
        if "morning" in hotel_by_slot:
            m = hotel_by_slot["morning"]
            m_start = int(m.get("start_min") or 0)
            m_end = int(m.get("end_min") or 0)
            # R15（2026-11-21 用户令「去程 8:30、出租 16，为什么从酒
            # 酒店出发时 7:15」FIX）：
            # C-13 的晨窗起点是打包窗（ready−60 起），晨卡要显示的却是
            # 「离店时刻」=班次−打车（C-13 ready 同语义）。带去程班次的日子
            # 把晨卡收成离店点卡；打车分钟=档案值（缺省网关口径，与
            # C-06/C-08/C-13 约束同源——去程打车卡同读此值）。R16：离店再减
            # 叫车 15 与强约束缓冲 15（乘车点候车）——去程打车卡跨度=叫车+
            # 车程、卡尾=班次前 15 分。
            if day_outbounds:
                _dep, _taxi = min(day_outbounds, key=lambda p: p[0])
                _ready = (
                    int(_dep)
                    - int(_taxi)
                    - TAXI_HAIL_MINUTES
                    - SHUTTLE_BOARD_BUFFER_MINUTES
                )
                if _ready > 0:
                    m_start = m_end = _ready
            if m_end >= m_start and m_end > 0:
                items.insert(
                    0,
                    VisitItem(
                        item_id="hotel-morning-d%d" % day_no,
                        name="🏨 从酒店出发",
                        name_en="🏨 Depart from hotel",
                        category="hotel",
                        city=label,
                        day=day_no,
                        start_time=_hhmm(m_start),
                        end_time=_hhmm(m_end),
                        duration_minutes=m_end - m_start,
                        synthetic=True,
                        soft_pin=True,
                    ),
                )
        if "night" in hotel_by_slot:
            n = hotel_by_slot["night"]
            n_start = int(n.get("start_min") or 0)
            n_end = int(n.get("end_min") or 0)
            # R13o：夜卡收口 DAY_END（21:30）——C-13 的 night_end 是
            # min(start+60, 23:59)，正常日 21:00-22:00 会吃评分器日终
            # 越界罚（overrun -60/卡，影子 plan_score 门实测漂-60）。
            _day_end = 21 * 60 + 30
            if n_end > _day_end:
                n_end = _day_end
            if n_start >= n_end:
                n_start = max(0, n_end - 30)
            if n_end > n_start:
                items.append(
                    VisitItem(
                        item_id="hotel-night-d%d" % day_no,
                        name="🏨 回酒店·夜间休息",
                        name_en="🏨 Return to hotel for the night",
                        category="hotel",
                        city=label,
                        day=day_no,
                        start_time=_hhmm(n_start),
                        end_time=_hhmm(n_end),
                        duration_minutes=n_end - n_start,
                        synthetic=True,
                        soft_pin=True,
                    )
                )
        days.append(DayPlan(day=day_no, base_city=label, items=items))

    # R13o①（R13n 审计最重项）：城际腿卡——引擎从不物化 TransferItem，
    # 跨城行程无车次/航班卡、无订票/改乘按钮（legacy 有）。结构卡：城市序
    # 转场日的日始头卡，方式按距离闸（>600km 航班、≤600km 火车——legacy
    # auto 同口径），时长按拍板「火车 2h/飞机 2.5h」；compact_days 以其为
    # 固定屏障把当天可动卡右推；班次号经既有 /transfers/{item_id}/tno
    # 端点回填真实车次。
    def _city_coord(city: str):
        from app.services.weather_open_meteo import CITY_COORDS

        return CITY_COORDS.get(str(city or "").removesuffix("市"))

    for _i in range(1, len(days)):
        _prev_city = days[_i - 1].base_city
        _cur_city = days[_i].base_city
        if not _prev_city or not _cur_city or _prev_city == _cur_city:
            continue
        if not days[_i].items or isinstance(days[_i].items[0], TransferItem):
            continue
        _mode = "train"
        _minutes = 120
        try:
            from ..inputs.travel import haversine_km

            _a = _city_coord(_prev_city)
            _b = _city_coord(_cur_city)
            if _a and _b:
                # CITY_COORDS 值是 (lat, lon) 元组；haversine_km 收标量。
                _km = haversine_km(_a[1], _a[0], _b[1], _b[0])
                if _km > 600:
                    _mode = "flight"
                    _minutes = 150
        except Exception:  # noqa: BLE001 - 距离判失败退火车口径
            pass
        _dep = 8 * 60 + 30  # 日始（DAY_START_MINUTES 同值）
        days[_i].items.insert(
            0,
            TransferItem(
                item_id="xfer-d%d" % days[_i].day,
                day=days[_i].day,
                seq=0,
                from_city=_prev_city,
                to_city=_cur_city,
                mode=_mode,
                start_time=_hhmm(_dep),
                end_time=_hhmm(_dep + _minutes),
                duration_minutes=_minutes,
            ),
        )

    # 闭合行程返程腿（2026-11-22，北京→西安→北京 不再回不了家）：城市序
    # 首尾同名时，末日必须有一条尾城→出发城的返程腿。上面的标签扫描只在
    # 「末日标签恰好翻回出发城」时出腿——末日是轻日、多数标签仍停在目的
    # 城时静默漏腿（行程停在西安，用户实报口径）。这里兜底：末日无城际腿
    # 就补一条（傍晚 17:00 窗=legacy 返程窗口径，白天归末位目的地；compact
    # 以其为固定屏障右推当天可动卡）。
    def _norm_city(c: str) -> str:
        return str(c or "").strip().removesuffix("市")

    _req_cities = [c for c in (snapshot.request.cities or ()) if c]
    if len(_req_cities) > 1 and _norm_city(_req_cities[0]) == _norm_city(
        _req_cities[-1]
    ):
        _last_day = days[-1]
        _has_leg = any(
            isinstance(i, TransferItem) for i in (_last_day.items or [])
        )
        _from_city = _last_day.base_city
        if (
            not _has_leg
            and _from_city
            and _norm_city(_from_city) != _norm_city(_req_cities[0])
        ):
            _ret_mode = "train"
            _ret_minutes = 120
            try:
                from ..inputs.travel import haversine_km

                _a = _city_coord(_from_city)
                _b = _city_coord(_req_cities[0])
                if _a and _b:
                    _km = haversine_km(_a[1], _a[0], _b[1], _b[0])
                    if _km > 600:
                        _ret_mode = "flight"
                        _ret_minutes = 150
            except Exception:  # noqa: BLE001 - 距离判失败退火车口径
                pass
            _ret_dep = 17 * 60  # legacy 返程窗（15:00-21:00）中点口径
            _ret_card = TransferItem(
                item_id="xfer-return-d%d" % _last_day.day,
                day=_last_day.day,
                seq=1,
                from_city=_from_city,
                to_city=_req_cities[0],
                mode=_ret_mode,
                start_time=_hhmm(_ret_dep),
                end_time=_hhmm(_ret_dep + _ret_minutes),
                duration_minutes=_ret_minutes,
            )
            # 返程腿殿后（列表序≈时间序）：白天游玩卡在前，傍晚回城收尾。
            _last_day.items.append(_ret_card)

    # R17（2026-11-22 用户实录「第四天西安→北京，酒店应该住北京，测试显示
    # 西安」）：夜卡/晨卡城市上面按 `_day_label`（当日多数城）落——跨城日到达
    # 城的卡还没排进来时多数城仍是出发城，夜卡于是写「西安」，次日晨卡继承它
    # 继续错。城际腿卡此刻已插好，按唯一口径（末段到达城优先）把占位酒店卡
    # 的城市拨正（已验证真实酒店不动）。
    apply_stay_cities(days)

    # R18：升旗真值落卡（fixed_sessions + 起止对齐）——必须在计划返回前，
    # assemble 的 compact/右推都以卡上锚为准。
    _apply_flag_anchors(days, snapshot)

    cand_by_rid: dict[str, object] = {}
    for cand in snapshot.candidates:
        if cand.rid and cand.rid not in cand_by_rid:
            cand_by_rid[cand.rid] = cand
    unplaced_rows = []
    for entry in solution.unplaced:
        cand = cand_by_rid.get(str(entry.get("rid") or ""))
        unplaced_rows.append(
            UnplacedCandidate(
                name=str(entry.get("name") or ""),
                poi_id=getattr(cand, "poi_id", None),
                category=getattr(cand, "category", None),
                tier=getattr(cand, "tier", None),
                duration_minutes=getattr(cand, "suggested_duration_min", None),
                reason=str(entry.get("reason") or ""),
            )
        )
    must_rids = {m.rid: m.name for m in snapshot.request.musts}
    unplaced_rids = {str(entry.get("rid") or "") for entry in solution.unplaced}
    unarranged = [name for rid, name in must_rids.items() if rid in unplaced_rids]

    plan = ItineraryPlan(
        itinerary_id=itinerary_id or ("it-%s" % snapshot_hash(snapshot)[:12]),
        cities=list(snapshot.request.cities),
        days=days,
        unplaced=unplaced_rows,
        unarranged_musts=unarranged,
        start_date=snapshot.request.start_date,
    )
    ensure_unique_item_ids(plan)
    return plan


def assemble(
    solution: "Solution",
    snapshot: "FactSnapshot",
    *,
    lang: str = "zh",
    itinerary_id: Optional[str] = None,
) -> ItineraryPlan:
    """F-30 -> F-31 -> F-32 -> F-33 in order (annotate_legs materialises
    display legs + fares); F-34 projections are derived separately in
    sync.py; F-33 lines also ride on the solution via
    render_disclosures so both langs stay derivable."""
    from .chips import attach_alternatives
    from .disclosures import render_disclosures
    from .meals import attach_meal_cards

    plan = materialize_plan(solution, snapshot, itinerary_id=itinerary_id)
    plan = attach_meal_cards(plan, solution, snapshot)
    plan = compact_days(plan, snapshot)
    # R13o①：城际腿屏障日右推（compact 只拉左；腿卡是装配期屏障）。
    plan = push_after_intercity(plan)
    plan = attach_alternatives(plan, snapshot)
    from ...itinerary.legs import annotate_legs

    plan = annotate_legs(plan)  # F-30 display legs + fare materialisation
    # R12 交通桥卡改为响应件（与回城卡同契约）：装配期不挂——
    # api._plan_for_response 在下发副本上幂等挂载，session/持久态
    # 零桥卡（编辑校验/挪位/LLM 卡单不受渲染件扰动）。
    plan.assumptions = render_disclosures(solution, snapshot, lang=lang)
    return plan
