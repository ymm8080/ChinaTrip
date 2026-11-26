"""C-05..C-08 constraints (P1-C2).

C-05 endpoint days: arrival/departure days exist ONLY with a timed intercity
leg (438bcfa). arrival_time → day-1 starts ≥ arrival+ARRIVAL_FLOOR_MINUTES;
departure_time → last day ends ≤ dep-DEPARTURE_BUFFER_MINUTES. No transport
info = full day (nothing added).

C-06 remote-day exclusivity — refined by the 24379abd hotfix evidence:
on a day holding a remote item (access profile present), other requested
candidates are allowed ONLY as ≤1 city morning anchor (start ≤ 10:30,
before the outbound access leg); unrequested fill is never placed there
(C-15 effect). Same-cluster remote items are unconstrained. A naive
"same-cluster or empty" rule would forbid the E-1 morning anchor, so it is
NOT the rule — the morning anchor is the exception that makes 天安门 →
慕田峪 legal.

C-07 city coherence: candidates with different `city` values never share a
day (single-city snapshots are unconstrained). Multi-city order itself is
an intent-layer input (Q6).

C-08 access legs as intervals (conservative, same semantics as the legacy
hotfix): for a remote candidate with an access profile, access arrival is
pinned to a timetable departure: arrival == dep + ride + last_mile; the
visit either starts there or after same-site lunch (F-22). A morning anchor
must finish + taxi before dep; the return leg starts ≥ visit.end +
RETURN_BUFFER and arrives back in the city. Pairs involving a profiled
remote candidate are excluded from the generic C-03 matrix disjunction (the
profile replaces it). Post-return non-cluster items are already impossible
by C-06, so no extra after-return ordering is needed for visits; dinner has
an explicit after-return constraint in C-10/F-22.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from ...itinerary.rules import (
    SHUTTLE_BOARD_BUFFER_MINUTES,
    TAXI_HAIL_MINUTES,
    TRAVEL_GAP_FLOOR_MIN,
    taxi_leg_min,
)
from ..inputs.access import hhmm_to_min
from .vars import MINUTES_PER_DAY, VarBundle

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot

from app.services.itinerary.models import arrival_buffer_minutes

ARRIVAL_FLOOR_MINUTES = 150  # 无交通模式地板（2026-11-18 拍板后与飞机同值）
DEPARTURE_BUFFER_MINUTES = 90


def arrival_floor_for(mode: str | None) -> int:
    """跨管线对齐（2026-11-18 拍板「火车 2h/飞机 2.5h」）：train 120 /
    flight 150（models.arrival_buffer_minutes 同源），无模式 150。"""
    if (mode or "").strip().lower() in ("flight", "train"):
        return arrival_buffer_minutes(mode)
    return ARRIVAL_FLOOR_MINUTES


MORNING_ANCHOR_CAP = 10 * 60 + 30  # 晨锚最迟 10:30
RETURN_BUFFER_MINUTES = 8
DEFAULT_GATEWAY_TAXI_MINUTES = 15
# R12-H4（2026-11-20 用户拍板「默认最早 SHUTTLE bus 8:30」）：出程
# 班车默认下限 08:30——更早的行不进可排面（fail-open：全滤空时保
# 留原行防不可解）。
DEFAULT_FIRST_SHUTTLE_MIN = 8 * 60 + 30


def _return_tail_minutes(other) -> int:
    """回城落点 → 同日下一站的打车尾段（R38，2026-11-25）。

    此前 C-08 的「返程后」支锚在 ``min(rets)+ride+last_mile``（时刻表最早
    班）且不含尾段：求解器实际选中的返程班更晚时，下一站被允许排到早于
    真实到达（day3 慕田峪 16:30 班 18:08 到前门、奥园被排 17:30 的实锤；
    C-06 让位日 C-08 独守顺序，此处是唯一闸）。落点无独立坐标，用城市锚
    代理（materialize._city_coord 同源 CITY_COORDS）；口径与
    rules.taxi_leg_min 同式（近距步行 / 打车=车程+叫车 / 毒坐标封顶）。
    """
    o_lon = getattr(other, "lon", None)
    o_lat = getattr(other, "lat", None)
    if o_lon is None or o_lat is None:
        return TRAVEL_GAP_FLOOR_MIN
    from app.services.weather_open_meteo import CITY_COORDS

    anchor = CITY_COORDS.get(str(getattr(other, "city", None) or "").removesuffix("市"))
    if anchor is None:
        return TRAVEL_GAP_FLOOR_MIN
    from ..inputs.travel import haversine_km

    km = haversine_km(anchor[1], anchor[0], o_lon, o_lat)
    if km <= 0.5:  # SAME_VENUE_KM 同址：出站即到
        return 0
    return taxi_leg_min(km)


# R12-H24：远郊日「插一个」=小点专用（大必去留城内簇日）
LEFTOVER_MAX_MINUTES = 120


def _hhmm(text: str | None) -> int | None:
    if not text:
        return None
    return hhmm_to_min(text)


def _profile_keys(enriched: "EnrichedSnapshot") -> set[str]:
    return set(enriched.access_by_poi.keys())


def _bound_to_remote(candidate, remote) -> bool:
    """A real restaurant bound to this remote site follows F-22, not the
    city morning-anchor rules."""
    target = getattr(candidate, "same_venue", None)
    return bool(target) and target in (remote.cid, remote.poi_id)


def add_c05_endpoints(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    request = enriched.snapshot.request
    arrival = _hhmm(getattr(request, "arrival_time", None))
    departure = _hhmm(getattr(request, "departure_time", None))
    arrival_floor = arrival_floor_for(getattr(request, "arrival_mode", None))
    departure_buffer = arrival_floor_for(getattr(request, "departure_mode", None))
    # R9-2：到达/离开日定位（None=首/末，S1 前默认端点）——中途转移日
    # （D2 才到/D3 就走）的地板/顶盖落在该日，天窗外全天窗（legacy
    # 撤腿重排同语义）
    arrival_day = getattr(request, "arrival_day", None) or (
        bundle.days[0] if bundle.days else None
    )
    departure_day = getattr(request, "departure_day", None) or (
        bundle.days[-1] if bundle.days else None
    )
    if arrival is not None and arrival_day in bundle.days:
        floor = arrival + arrival_floor
        for cand in enriched.snapshot.candidates:
            lit = bundle.presence[(cand.cid, arrival_day)]
            bundle.model.Add(
                bundle.start[(cand.cid, arrival_day)] >= floor
            ).OnlyEnforceIf(lit)
    if departure is not None and departure_day in bundle.days:
        cap = departure - departure_buffer
        for cand in enriched.snapshot.candidates:
            lit = bundle.presence[(cand.cid, departure_day)]
            bundle.model.Add(
                bundle.start[(cand.cid, departure_day)] + bundle.dur[cand.cid] <= cap
            ).OnlyEnforceIf(lit)
    elif departure_day in bundle.days:
        # 2026-11-22 闭合行程返程顶盖（北京→西安→北京 不再回不了家的
        # 模型侧配套）：首尾同名（闭合）且用户没给离开时刻时，装配层会在
        # 末日补傍晚返程腿（17:00 口径）——模型侧末日游玩收尾必须给赶车
        # 留缓冲（departure_buffer 同口径），否则装配腿与晚餐/晚卡重叠。
        # 闭合尾城填 ≥2 天=真实停留（797f350 口径）时末日无返程腿，
        # 不加顶盖（尾窗是完整游玩日）——closed_return_day 统一裁决。
        from .c17_city_days import closed_return_day

        if (
            closed_return_day(request.cities, request.days, request.city_days)
            == departure_day
        ):
            cap = 17 * 60 - departure_buffer
            for cand in enriched.snapshot.candidates:
                lit = bundle.presence[(cand.cid, departure_day)]
                bundle.model.Add(
                    bundle.start[(cand.cid, departure_day)] + bundle.dur[cand.cid]
                    <= cap
                ).OnlyEnforceIf(lit)


def add_c06_remote_exclusivity(
    bundle: VarBundle, enriched: "EnrichedSnapshot", relax: bool = False
) -> None:
    """C-06 R12-H5（2026-11-20 用户拍板「删景点也是按删的规则。首先按
    地理聚族，远郊优先好天，单日就先排长城。然后时间有多余就插一个
    景点。第二天排剩下的。如果排不上按规则删」）：远郊日=长城优先
    （班次链自带），**时间多余才插一个景点**——插入卡（请求点或池
    内补点，至多一个）必须在返程到城之后开场（真余量；F4b 日预算继
    续把关「只有空闲才插」）；同簇远郊卡不占额；同址餐归 F-22；餐/
    宿/交通类不占额；用户钉在本日的卡豁免（铁律 19——C-08 以
    dep≥end+taxi 绕行链序）。
    ``relax=True`` is F-25 rung 5 (disclosed) — skipped entirely.

    R31: an explicit user-authored day plan (C-25 ``day_hint`` blocks)
    outranks this default heuristic. When the user wrote "put these stops on
    day N", C-06's hard "at most one small extra on a remote day" cap makes
    that very grouping infeasible; the min-drop ladder then discarded the
    must-visits (e.g. 什刹海 / 鸟巢(国家体育场) with 慕田峪 on one written day)
    while the day still had free hours. So the heuristic yields wholesale
    for such requests. Physical access ordering is NOT lost — C-08
    (``add_c08_access``) independently enforces "finish before the outbound
    shuttle or start after the return" for every profiled remote item.
    """
    if relax:
        return
    from .c25_must_days import has_user_day_blocks

    snapshot = enriched.snapshot
    profiled = _profile_keys(enriched)
    remote_cands = [c for c in snapshot.candidates if (c.poi_id or c.cid) in profiled]

    def _esc_pairs_for_day(day: int) -> list:
        return [
            (c.cid, bundle.cap_escapes[(c.cid, day)])
            for c in snapshot.candidates
            if (c.cid, day) in bundle.cap_escapes
        ]

    def _bind_escape_existence(day: int):
        # R36 存在性锚（R12-H22 语义收口）：esc ⇒ OR(各远郊在场)——
        # 「远郊日」是存在性语义，与远郊只数无关；此前该蕴涵错挂在逐
        # 远郊循环里，≥2 远郊时被写成「每个远郊都在场」，逃逸位恒死
        # （慕田峪+八达岭同请求即触发，可丢必去）。无远郊 ⇒ esc 钉 0
        # （C-02 契约「无远郊日的 esc 被 C-06 钉死为 0」——此前的两条
        # 让位路径 esc 都是自由布尔，闸被整体架空）。返回日级聚合布尔
        # （无远郊返回 None）。esc ⇒ 自身在场的绑定也在此统一提走。
        pairs = _esc_pairs_for_day(day)
        if not pairs:
            return None
        remote_day = None
        if remote_cands:
            remote_day = bundle.model.NewBoolVar("c06rd_%d" % day)
            bundle.model.AddMaxEquality(
                remote_day,
                [bundle.presence[(r.cid, day)] for r in remote_cands],
            )
        for cid, esc in pairs:
            bundle.model.AddImplication(esc, bundle.presence[(cid, day)])
            if remote_day is not None:
                bundle.model.AddImplication(esc, remote_day)
            else:
                bundle.model.Add(esc == 0)
        return remote_day

    if has_user_day_blocks(enriched.snapshot.request):
        bundle.c06_yielded_to_day_plan = True
        # R31 让位 ≠ esc 失义（R36 最小锚）：只保「远郊日在场」存在性
        # 与每日至多一张逃逸卡；独占/quota 等强约束不回来（R35 二分
        # PROVEN INFEASIBLE 的根因正是 quota 锚过强 + 多远郊全绑定）。
        for day in bundle.days:
            escs = [esc for _cid, esc in _esc_pairs_for_day(day)]
            _bind_escape_existence(day)
            if len(escs) > 1:
                bundle.model.Add(sum(escs) <= 1)
        return

    if not remote_cands:
        for day in bundle.days:
            _bind_escape_existence(day)  # 无远郊：esc 全钉 0（R36）
        return
    request = snapshot.request
    pinned_by_day: dict[int, set[str]] = {}
    for pin in getattr(request, "pins", ()) or ():
        for c in snapshot.candidates:
            if pin.rid == c.rid or (pin.cid and pin.cid == c.cid):
                pinned_by_day.setdefault(pin.day, set()).add(c.cid)
    for day in bundle.days:
        # R36：存在性锚逐日一次——esc ⇒ OR(各远郊在场) + esc ⇒ 自身
        # 在场的绑定自逐远郊循环提走后，主路径统一在这里挂上。
        _bind_escape_existence(day)
        pinned_here = pinned_by_day.get(day, set())
        for rid_cand in remote_cands:
            lr = bundle.presence[(rid_cand.cid, day)]
            key = rid_cand.poi_id or rid_cand.cid
            profile = enriched.access_by_poi.get(key)
            back = int(getattr(profile, "ride_minutes", 0) or 0) + int(
                getattr(profile, "last_mile_minutes", 0) or 0
            )
            # 无返程表（合成夹具）时回退锚=游览尾+回程（仍在返程后）
            ret = bundle.active_ret_vars.get((rid_cand.cid, day))
            if ret is not None:
                floor_expr = ret + back
            else:
                floor_expr = (
                    bundle.start[(rid_cand.cid, day)] + bundle.dur[rid_cand.cid] + back
                )
            extras: list = []
            for other in snapshot.candidates:
                if other.cid == rid_cand.cid:
                    continue
                # R12-H22b/R36：逃逸钉底（esc ⇒ 他卡在场 ∧ 远郊日在场）
                # 已提升为逐日一次的 _bind_escape_existence——在这里写
                # esc ⇒ lr 会随远郊只数漂移成「每个远郊都在场」（≥2 远
                # 郊时逃逸位恒死），存在性语义必须聚合在循环外。
                if (other.poi_id or other.cid) in profiled:
                    continue  # same remote cluster: allowed
                if _bound_to_remote(other, rid_cand):
                    continue  # same-site remote meal, governed by F-22
                if (other.category or "") in (
                    "food",
                    "hotel",
                    "transport",
                    "transfer",
                ):
                    continue  # 结构卡不占「一个景点」额
                if other.cid in pinned_here:
                    continue  # 铁律19：钉在本日=用户意志，链序绕行
                lit = bundle.presence[(other.cid, day)]
                if (other.suggested_duration_min or 0) > LEFTOVER_MAX_MINUTES:
                    # R12-H24（2026-11-20 用户拍板「本来就是按重要度和地
                    # 理分三族…时间有富裕可以回插一个 MUST VISIT 小景
                    # 点」）：远郊日只装小点（≤120）——大必去留城内簇日，
                    # 绝不挤长城日余量槽。
                    bundle.model.Add(lit == 0).OnlyEnforceIf(lr)
                    continue
                extras.append(lit)
                # R12-H13：远郊日的「一个」=晨锚（出发前收完，如升旗
                # 天安门 06:30-08:00→08:30 班车=语料正典形状）或返程到城
                # 后的真余量——两支析取，C-08 dep≥end+taxi 同款把关。
                dep_var = bundle.dep_vars.get((rid_cand.cid, day))
                if dep_var is not None and ret is not None:
                    _aft = bundle.model.NewBoolVar(
                        "c06a_%s_%s_%d" % (rid_cand.cid, other.cid, day)
                    )
                    # R12-H22/R36：余量槽闸豁免——esc 只许在返程后支上，
                    # 且改挂「实际在场的那只远郊」：(esc ∧ 本远郊在场) ⇒
                    # aft；lit/lr 的存在性绑定已由 _bind_escape_existence
                    # 统一提走（逐远郊无条件 esc ⇒ aft/lit/lr 在多远郊时
                    # 会把存在性写成全称）。
                    _esc = bundle.cap_escapes.get((other.cid, day))
                    if _esc is not None:
                        bundle.model.AddBoolOr([_aft.Not(), _esc.Not(), lr.Not()])
                    bundle.model.Add(
                        bundle.start[(other.cid, day)] >= floor_expr
                    ).OnlyEnforceIf([lit, lr, _aft])
                    bundle.model.Add(
                        bundle.start[(other.cid, day)]
                        + bundle.dur[other.cid]
                        + int(getattr(profile, "taxi_minutes", 0) or 0)
                        + TAXI_HAIL_MINUTES
                        + SHUTTLE_BOARD_BUFFER_MINUTES
                        <= dep_var
                    ).OnlyEnforceIf([lit, lr, _aft.Not()])
                else:
                    # 无班次链（合成夹具）：floor 在 [lit, lr] 下无条件
                    # 生效；esc 的存在性绑定已统一提走（R36），此处无需
                    # 逐远郊重复 esc ⇒ lit / esc ⇒ lr。
                    bundle.model.Add(
                        bundle.start[(other.cid, day)] >= floor_expr
                    ).OnlyEnforceIf([lit, lr])
            if extras:
                bundle.model.Add(sum(extras) <= 1).OnlyEnforceIf(lr)


def add_c07_city_coherence(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    candidates = enriched.snapshot.candidates
    for i, a in enumerate(candidates):
        if not getattr(a, "city", None):
            continue
        for b in candidates[i + 1 :]:
            if not getattr(b, "city", None) or a.city == b.city:
                continue
            for day in bundle.days:
                bundle.model.Add(
                    bundle.presence[(a.cid, day)] + bundle.presence[(b.cid, day)] <= 1
                )


def add_c08_access(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    profiled = _profile_keys(enriched)
    for cand in snapshot.candidates:
        key = cand.poi_id or cand.cid
        profile = enriched.access_by_poi.get(key)
        if profile is None:
            continue
        deps = [hhmm_to_min(d) for d in profile.departures]
        # R12-H4：默认最早班车 08:30（更早的行不进可排面，fail-open）
        # R19 (chosen-shuttle pin): a user-picked bus is explicit
        # user authority (iron-rule-19 semantics) -- a singleton
        # domain overrides the default 08:30 first-shuttle floor
        # (an early 07:30 pick must survive a re-solve). A stale
        # pick that is no longer in the timetable is ignored
        # (fail-open).
        if getattr(cand, "chosen_depart", None):
            _cdm = hhmm_to_min(str(cand.chosen_depart))
            deps = (
                [_cdm]
                if _cdm in deps
                else [m for m in deps if m >= DEFAULT_FIRST_SHUTTLE_MIN] or deps
            )
        else:
            deps = [m for m in deps if m >= DEFAULT_FIRST_SHUTTLE_MIN] or deps
        rets = [hhmm_to_min(d) for d in profile.returns]
        # R19: chosen return -- same user authority on the return
        # leg; the earliest-feasible chain degenerates to the
        # picked bus under a singleton domain.
        if getattr(cand, "chosen_return", None):
            _crm = hhmm_to_min(str(cand.chosen_return))
            if _crm in rets:
                rets = [_crm]
        if not deps:
            continue
        ride = int(profile.ride_minutes)
        last_mile = int(profile.last_mile_minutes or 0)
        taxi = int(getattr(profile, "taxi_minutes", 0) or 0)
        taxi = taxi or DEFAULT_GATEWAY_TAXI_MINUTES
        # R16：打车接硬班次=车程+叫车 15+强约束缓冲 15（2026-11-21
        # 用户拍板）——前序卡收尾到班车发车的硬余量同口径；旅程时间目标项仍计车程。
        board_chain = taxi + TAXI_HAIL_MINUTES + SHUTTLE_BOARD_BUFFER_MINUTES
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            dep = bundle.model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(deps), "dep_%s_%d" % (cand.cid, day)
            )
            bundle.dep_vars[(cand.cid, day)] = dep
            active_dep = bundle.model.NewIntVar(
                0, MINUTES_PER_DAY, "adep_%s_%d" % (cand.cid, day)
            )
            bundle.model.Add(active_dep == dep).OnlyEnforceIf(lit)
            bundle.model.Add(active_dep == 0).OnlyEnforceIf(lit.Not())
            bundle.active_dep_vars[(cand.cid, day)] = active_dep
            arrival = bundle.model.NewIntVar(
                0, MINUTES_PER_DAY, "arr_%s_%d" % (cand.cid, day)
            )
            bundle.arrival_vars[(cand.cid, day)] = arrival
            # 接驳到点独立于游览开始：F-22 可在同址先午餐再游览。
            bundle.model.Add(arrival == dep + ride + last_mile).OnlyEnforceIf(lit)
            # R38：返程班变量提前到 others 循环前创建——返程后支的锚必须用
            # 「求解器实际选中的班」（active_ret），不是时刻表最早班。
            ret = None
            active_ret = None
            if rets:
                ret = bundle.model.NewIntVarFromDomain(
                    cp_model.Domain.FromValues(rets), "ret_%s_%d" % (cand.cid, day)
                )
                bundle.ret_vars[(cand.cid, day)] = ret
                active_ret = bundle.model.NewIntVar(
                    0, MINUTES_PER_DAY, "aret_%s_%d" % (cand.cid, day)
                )
                bundle.model.Add(active_ret == ret).OnlyEnforceIf(lit)
                bundle.model.Add(active_ret == 0).OnlyEnforceIf(lit.Not())
                bundle.active_ret_vars[(cand.cid, day)] = active_ret
            # 晨锚必须先结束+打车，才允许赶这一班（C-06 的晨锚例外）
            for other in snapshot.candidates:
                if other.cid == cand.cid or not other.rid:
                    continue
                if (other.poi_id or other.cid) in profiled or _bound_to_remote(
                    other, cand
                ):
                    continue
                lo = bundle.presence[(other.cid, day)]
                # R12-H5 析取：他卡要么在出发前（dep ≥ end + taxi），要么
                # 在返程到城后（≥ 最早返程行+回程——C-06 的「时间多余才
                # 插一个」由此可排）；after 自由布尔，求解器按形状挑支。
                # 2026-11-23 兵马俑案：真库 poi_access_services 存在
                # outbound 有班、return 为空的行（北京 居庸关长城/八奇洞/
                # 古北口镇，上海 东林寺/州桥老街…）——ret 空时 min(rets)
                # 直接 ValueError，引擎整缝崩、回落 legacy（兵马俑未排根
                # 因链）。「返程后」支不存在：他卡只可能在发车前收尾。
                if rets:
                    after = bundle.model.NewBoolVar(
                        "aft_%s_%s_%d" % (cand.cid, other.cid, day)
                    )
                    bundle.model.Add(
                        dep
                        >= bundle.start[(other.cid, day)]
                        + bundle.dur[other.cid]
                        + board_chain
                    ).OnlyEnforceIf([lit, lo, after.Not()])
                    # R38：锚=求解器实际选中的返程班+落点→下一站尾段——
                    # 此前 min(rets)（最早班）且无尾段，选中班更晚时下一站
                    # 可早于真实到达开场（day3 慕田峪奥园案）。与 C-06
                    # floor(ret+back)、C-09 晚饭锚同口径。
                    bundle.model.Add(
                        bundle.start[(other.cid, day)]
                        >= active_ret + ride + last_mile + _return_tail_minutes(other)
                    ).OnlyEnforceIf([lit, lo, after])
                else:
                    bundle.model.Add(
                        dep
                        >= bundle.start[(other.cid, day)]
                        + bundle.dur[other.cid]
                        + board_chain
                    ).OnlyEnforceIf([lit, lo])
            bundle.travel_terms.append(lit * (2 * (ride + last_mile) + taxi))
            if not rets:
                continue
            # 返程腿：散场+缓冲 → 回城（回城后的非簇件已被 C-06 禁掉；
            # ret/active_ret 已提前到 others 循环前创建——R38）
            bundle.model.Add(
                ret
                >= bundle.start[(cand.cid, day)]
                + bundle.dur[cand.cid]
                + RETURN_BUFFER_MINUTES
            ).OnlyEnforceIf(lit)
            # R12-H17（2026-11-20 用户拍板「慕田峪 13:28 结束应该搭乘
            # 14:30 的 SHUTTLE BUS」）：返程=**最早可行班**（游览收尾+8
            # 分钟缓冲后最早一班）——硬约束不经末层拉引：等式锁会把
            # dtime 帽内的次优班次冻死（实锤：870 族三层全更优仍被
            # preference 层 23664 等式锁拒），早回城才有当天余量。
            _u_prev = None
            for _r in sorted(set(rets)):
                _u = bundle.model.NewBoolVar("uret_%s_%d_%d" % (cand.cid, day, _r))
                bundle.model.Add(
                    bundle.start[(cand.cid, day)]
                    + bundle.dur[cand.cid]
                    + RETURN_BUFFER_MINUTES
                    <= _r
                ).OnlyEnforceIf([lit, _u])
                bundle.model.Add(
                    bundle.start[(cand.cid, day)]
                    + bundle.dur[cand.cid]
                    + RETURN_BUFFER_MINUTES
                    > _r
                ).OnlyEnforceIf([lit, _u.Not()])
                if _u_prev is None:
                    bundle.model.Add(ret == _r).OnlyEnforceIf([lit, _u])
                else:
                    bundle.model.Add(ret == _r).OnlyEnforceIf([lit, _u, _u_prev.Not()])
                _u_prev = _u


def extract_access_legs(
    bundle: VarBundle, enriched: "EnrichedSnapshot", solver
) -> list[dict]:
    """Read chosen departures back out for Solution.access_legs (card ≡ leg)."""
    out: list[dict] = []
    snapshot = enriched.snapshot
    for cand in snapshot.candidates:
        key = cand.poi_id or cand.cid
        profile = enriched.access_by_poi.get(key)
        if profile is None:
            continue
        ride = int(profile.ride_minutes)
        last_mile = int(profile.last_mile_minutes or 0)
        for day in bundle.days:
            if not solver.Value(bundle.presence[(cand.cid, day)]):
                continue
            dep_var = bundle.dep_vars.get((cand.cid, day))
            if dep_var is None:
                continue
            dep_min = solver.Value(dep_var)
            ret_var = bundle.ret_vars.get((cand.cid, day))
            ret_min = solver.Value(ret_var) if ret_var is not None else None
            start = solver.Value(bundle.start[(cand.cid, day)])
            dur = solver.Value(bundle.dur[cand.cid])
            arrival = solver.Value(bundle.arrival_vars[(cand.cid, day)])
            out.append(
                {
                    "cid": cand.cid,
                    "day": day,
                    "gateway": profile.gateway,
                    "depart_min": dep_min,
                    "arrive_poi_min": arrival,
                    "visit_start_min": start,
                    "visit_end_min": start + dur,
                    "return_depart_min": ret_min,
                    "arrive_city_min": (
                        ret_min + ride + last_mile if ret_min is not None else None
                    ),
                }
            )
    return out
