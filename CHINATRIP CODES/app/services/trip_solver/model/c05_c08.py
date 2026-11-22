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

from ...itinerary.rules import SHUTTLE_BOARD_BUFFER_MINUTES, TAXI_HAIL_MINUTES
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
    ``relax=True`` is F-25 rung 5 (disclosed) — skipped entirely."""
    if relax:
        return
    snapshot = enriched.snapshot
    profiled = _profile_keys(enriched)
    remote_cands = [c for c in snapshot.candidates if (c.poi_id or c.cid) in profiled]
    if not remote_cands:
        return
    request = snapshot.request
    pinned_by_day: dict[int, set[str]] = {}
    for pin in getattr(request, "pins", ()) or ():
        for c in snapshot.candidates:
            if pin.rid == c.rid or (pin.cid and pin.cid == c.cid):
                pinned_by_day.setdefault(pin.day, set()).add(c.cid)
    for day in bundle.days:
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
                # R12-H22b（天坛 1152>960 越闸实锤修复）：逃逸钉底——
                # esc ⇒ (他卡在场 ∧ 远郊日在场) 提到一切 continue 之前
                # （H24 大点分支曾绕过蕴涵让 esc 成自由变量、闸被白抬）；
                # 非远郊日/未在场恒 esc=0，闸照常。
                _esc_top = bundle.cap_escapes.get((other.cid, day))
                if _esc_top is not None:
                    _lit_top = bundle.presence[(other.cid, day)]
                    bundle.model.AddImplication(_esc_top, _lit_top)
                    bundle.model.AddImplication(_esc_top, lr)
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
                    # R12-H22：余量槽闸豁免——esc 只许在返程后支上
                    _esc = bundle.cap_escapes.get((other.cid, day))
                    if _esc is not None:
                        bundle.model.AddImplication(_esc, _aft)
                        bundle.model.AddImplication(_esc, lit)
                        bundle.model.AddImplication(_esc, lr)
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
                    bundle.model.Add(
                        bundle.start[(other.cid, day)] >= floor_expr
                    ).OnlyEnforceIf([lit, lr])
                    _esc = bundle.cap_escapes.get((other.cid, day))
                    if _esc is not None:
                        bundle.model.AddImplication(_esc, lit)
                        bundle.model.AddImplication(_esc, lr)
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
        deps = [m for m in deps if m >= DEFAULT_FIRST_SHUTTLE_MIN] or deps
        rets = [hhmm_to_min(d) for d in profile.returns]
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
                # 插一个」由此可排）；after 自由布尔，求解器按形状挑支
                after = bundle.model.NewBoolVar(
                    "aft_%s_%s_%d" % (cand.cid, other.cid, day)
                )
                bundle.model.Add(
                    dep
                    >= bundle.start[(other.cid, day)]
                    + bundle.dur[other.cid]
                    + board_chain
                ).OnlyEnforceIf([lit, lo, after.Not()])
                bundle.model.Add(
                    bundle.start[(other.cid, day)] >= min(rets) + ride + last_mile
                ).OnlyEnforceIf([lit, lo, after])
            bundle.travel_terms.append(lit * (2 * (ride + last_mile) + taxi))
            if not rets:
                continue
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
            # 返程腿：散场+缓冲 → 回城（回城后的非簇件已被 C-06 禁掉）
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
