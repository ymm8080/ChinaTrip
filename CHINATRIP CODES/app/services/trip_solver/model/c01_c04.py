"""C-01..C-04 constraints and full model assembly (P1-C1…P1-D).

C-01 opening windows + closed weekdays — window from the F-12 first-window
approximation; 周X关闭 parses from the hours text.
C-02 entry caps (990/930, exemptions resolved upstream in F-12).
C-03 pairwise travel disjunction: if two candidates share a day, one must
finish + travel before the other starts (matrix lookup, default 45).
C-04 pins (iron rule 19: exact day + start) and day1_start horizon shift.

F-23 objectives live in objectives.py and are solved lexicographically by
solve.py; this module only assembles hard constraints.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

from ..inputs.travel import haversine_km, lookup
from .slack import SlackFlags
from .vars import DAY_END_MINUTES, DAY_START_MINUTES, VarBundle, define_variables

# 铁律 7 对齐（P2-B3 iter2）：审计 travel_gap_needed = taxi_leg_min(km)
# = min(180, km×1.3绕行/35km/h×60) + 30 叫车；坐标对取
# max(矩阵, taxi(km))——保实测腿质量、不放过近距对；同址
# （≤SAME_VENUE_KM=solver 口径）免隔腿
SAME_VENUE_KM = 0.5
TAXI_SPEED_KMH = 35.0
TAXI_DETOUR = 1.3
TAXI_RIDE_CAP_MIN = 180
TAXI_CALL_MINUTES = 30

#: 升旗锚兜底（flag_schedule 空库 / 出发日期未定时）：静态 06:30。
FLAG_FALLBACK_MINUTES = 6 * 60 + 30


def _taxi_gap_minutes(km: float) -> int:
    """审计走行缝公式（rules.travel_gap_needed / solver._taxi_leg_min）。"""
    ride = min(TAXI_RIDE_CAP_MIN, round(km * TAXI_DETOUR / TAXI_SPEED_KMH * 60))
    return ride + TAXI_CALL_MINUTES


if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot

_CLOSED_RE = re.compile(r"周([一二三四五六日天])关闭")
_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def closed_weekdays(hours_text: str | None) -> frozenset[int]:
    return frozenset(
        _WEEKDAYS[m.group(1)] for m in _CLOSED_RE.finditer(hours_text or "")
    )


def day_date(start_date: str | None, day: int) -> date | None:
    if not start_date:
        return None
    try:
        base = date.fromisoformat(start_date)
    except ValueError:
        return None
    return base + timedelta(days=day - 1)


def _pinned_cids(request, snapshot) -> set[tuple[str, int]]:
    by_rid: dict[str, list[str]] = {}
    for cand in snapshot.candidates:
        if cand.rid:
            by_rid.setdefault(cand.rid, []).append(cand.cid)
    out: set[tuple[str, int]] = set()
    for pin in getattr(request, "pins", ()) or ():
        for cid in by_rid.get(pin.rid, []):
            out.add((cid, pin.day))
        if pin.cid:
            out.add((pin.cid, pin.day))
    return out


#: R23：bvt 槽位窗（start 须在窗内且 end=窗上界−dur；镜像 legacy
#: itinerary/solver.py:_BEST_VISIT_WINDOWS 的 morning/afternoon/sunset
#: 三槽——engine 专属机制已覆盖 evening（R20 软阶梯，fail-open 有意差异）/
#: sunrise（旗时等式，更强）/show（C-11 场次钉），三者刻意不入表）。
#: 放不下 → presence=0 弃卡，与 legacy unplaced 同形。
_BVT_SLOT_WINDOWS = {
    "morning": (DAY_START_MINUTES, 12 * 60),
    "afternoon": (12 * 60, 17 * 60),
    "sunset": (16 * 60, 19 * 60),
}


def add_c01_windows(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    model = bundle.model
    # 候选池级只算一次（铁律19 钉位集合与候选无关，逐候选重算是 O(n²)）。
    pinned_keys = _pinned_cids(snapshot.request, snapshot)
    flag_times = getattr(enriched, "flag_times", None) or {}
    for cand in snapshot.candidates:
        window = enriched.windows.get(cand.cid)
        closed = closed_weekdays(cand.opening_hours)
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            start = bundle.start[(cand.cid, day)]
            day_dt = day_date(snapshot.request.start_date, day)
            if day_dt is not None and day_dt.weekday() in closed:
                model.Add(lit == 0)  # 闭馆日不可排（C-01）
                continue
            lo = DAY_START_MINUTES
            hi = 23 * 60 if cand.best_visit_time == "show" else DAY_END_MINUTES
            flag_min: int | None = None
            if (cand.best_visit_time or "") == "sunrise":
                # R12-H11/H25 / R18（2026-11-22 用户令「不可能没有升旗
                # 时间」）：晨锁带锚=flag_schedule 批次库真值（07:10 实
                # 测）。空库回落静态 06:30。
                lo = FLAG_FALLBACK_MINUTES
                _ft = flag_times.get(day)
                if _ft:
                    lo = int(_ft)
                    flag_min = int(_ft)
            if (cand.cid, day) in pinned_keys:
                # 铁律19：钉住时刻不受 08:30 日始钳制（升旗/班次类）；
                # 钉位自带钟点，旗时等式让位（两钟点不重合时不许互撞
                # 成 infeasible）。
                lo = window[0] if window is not None else 0
                flag_min = None
            if window is not None:
                lo = max(lo, window[0])
                hi = min(hi, window[1])
            _slot = _BVT_SLOT_WINDOWS.get((cand.best_visit_time or "").lower())
            if _slot is not None:
                # R23：晨景/午后/黄昏槽位窗（end 落窗内），镜像 legacy 钳制。
                lo = max(lo, _slot[0])
                hi = min(hi, _slot[1])
            if flag_min is not None and flag_min >= lo:
                # R18：升旗=官方固定钟点，不是「≥ 下界」——下界语义下 C-04
                # 落地地板（到达 08:15）把开场推到 09:30，卡上再没有升旗
                # 时刻（2026-11-22 实录）。等式语义把「当天赶不上」变成
                # presence=0，由覆盖约束换天（Day2 07:11），而不是排成一
                # 张没有旗时的广场卡。
                model.Add(start == flag_min).OnlyEnforceIf(lit)
            else:
                model.Add(start >= lo).OnlyEnforceIf(lit)
            model.Add(start + bundle.dur[cand.cid] <= hi).OnlyEnforceIf(lit)


def add_c02_caps(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    # R12-H16b/H22：入场闸硬口径，唯一豁免=远郊日返程后的「插一个」
    # 设计位（用户拍板「第一天回城有富裕时间为么不可以加天坛」）。
    # escape 布尔在此创建，C-06 填约束（esc ⇒ 远郊在场+返程后支+当日
    # ≤1 槽——extras 计数同一环）；无远郊日的 esc 被 C-06 钉死为 0。
    remote_keys = set(enriched.access_by_poi.keys())
    for cand in enriched.snapshot.candidates:
        cap, _reason = enriched.caps.get(cand.cid, (None, "unknown"))
        if cap is None:
            continue
        is_remote = (cand.poi_id or cand.cid) in remote_keys
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            if is_remote:
                bundle.model.Add(bundle.start[(cand.cid, day)] <= cap).OnlyEnforceIf(
                    lit
                )
                continue
            esc = bundle.model.NewBoolVar("capes_%s_%d" % (cand.cid, day))
            bundle.cap_escapes[(cand.cid, day)] = esc
            # R12-H23：入场闸弹性 +30（读闸 enforce_entry_gate 同口径
            # ——2026-11-16 拍板「diff within 30 minutes, accept」）
            from ..inputs.hours_caps import ENTRY_FLEX_MINUTES as _EFL

            bundle.model.Add(bundle.start[(cand.cid, day)] <= cap + _EFL).OnlyEnforceIf(
                [lit, esc.Not()]
            )


def add_c03_travel(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    candidates = enriched.snapshot.candidates
    keys = {c.cid: (c.poi_id or c.cid) for c in candidates}
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            if (
                keys[a.cid] in enriched.access_by_poi
                or keys[b.cid] in enriched.access_by_poi
            ):
                continue  # C-08 接驳区间替代通用矩阵析取（P1-C2）
            a_host = getattr(a, "same_venue", None)
            b_host = getattr(b, "same_venue", None)
            if (a_host and a_host in (b.cid, b.poi_id)) or (
                b_host and b_host in (a.cid, a.poi_id)
            ):
                continue  # C-09 同址嵌套，不做旅行析取
            km = (
                haversine_km(a.lon, a.lat, b.lon, b.lat)
                if a.lon is not None
                and a.lat is not None
                and b.lon is not None
                and b.lat is not None
                else None
            )
            if km is not None and km <= SAME_VENUE_KM:
                # 同址免隔腿但仍禁重叠（audit rule 1：非餐卡不可
                # 同刻）——零车程析取而非跳过（iter3 修正）
                ab, ba = 0, 0
            if a.city and b.city and a.city != b.city:
                # R3d: 跨城对同日共现已被 C-07 全禁，逐日析取冗余；
                # 剪掉 O(n²×days) 的顺序布尔（g11 6070 变量主成本）
                continue
            ab = lookup(enriched.matrix, keys[a.cid], keys[b.cid])
            ba = lookup(enriched.matrix, keys[b.cid], keys[a.cid])
            if km is not None:
                need = _taxi_gap_minutes(km)
                ab = max(ab, need)
                ba = max(ba, need)
            for day in bundle.days:
                pa = bundle.presence[(a.cid, day)]
                pb = bundle.presence[(b.cid, day)]
                if pa is pb:
                    continue
                order = bundle.model.NewBoolVar("o_%s_%s_%d" % (a.cid, b.cid, day))
                both = bundle.model.NewBoolVar("both_%s_%s_%d" % (a.cid, b.cid, day))
                bundle.model.AddBoolAnd([pa, pb]).OnlyEnforceIf(both)
                bundle.model.AddBoolOr([pa.Not(), pb.Not()]).OnlyEnforceIf(both.Not())
                bundle.model.Add(order <= pa)
                bundle.model.Add(order <= pb)
                sa = bundle.start[(a.cid, day)]
                sb = bundle.start[(b.cid, day)]
                bundle.model.Add(sb >= sa + bundle.dur[a.cid] + ab).OnlyEnforceIf(
                    [pa, pb, order]
                )
                bundle.model.Add(sa >= sb + bundle.dur[b.cid] + ba).OnlyEnforceIf(
                    [pa, pb, order.Not()]
                )
                bundle.travel_terms.append(ba * both + (ab - ba) * order)


def add_c04_pins(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    request = enriched.snapshot.request
    for pin in getattr(request, "pins", ()) or ():
        cids = bundle.rid_cids.get(pin.rid) or ([pin.cid] if pin.cid else [])
        if not cids:
            raise ValueError("pin %r references no candidate" % pin.rid)
        for cid in cids:
            for day in bundle.days:
                lit = bundle.presence[(cid, day)]
                if day == pin.day:
                    bundle.model.Add(lit == 1)
                    # iron rule 19: the pin's clock is objective, not horizon-bound
                    bundle.model.Add(bundle.start[(cid, day)] == pin.start_min)
                else:
                    bundle.model.Add(lit == 0)
    if request.day1_start:
        hh, mm = request.day1_start.split(":")
        floor = int(hh) * 60 + int(mm)
        for cand in enriched.snapshot.candidates:
            lit = bundle.presence[(cand.cid, 1)]
            if 1 in bundle.days:
                bundle.model.Add(bundle.start[(cand.cid, 1)] >= floor).OnlyEnforceIf(
                    lit
                )


def build_model(
    enriched: "EnrichedSnapshot", slack: "SlackFlags | None" = None
) -> VarBundle:
    from .c05_c08 import (
        add_c05_endpoints,
        add_c06_remote_exclusivity,
        add_c07_city_coherence,
        add_c08_access,
    )

    flags = slack or SlackFlags()
    bundle = define_variables(enriched)
    if flags.drop_fill:
        # F-25 rung 1: fills forced absent (vars stay for lookups).
        for cand in enriched.snapshot.candidates:
            if cand.rid:
                continue
            for day in bundle.days:
                bundle.model.Add(bundle.presence[(cand.cid, day)] == 0)
    add_c01_windows(bundle, enriched)
    add_c02_caps(bundle, enriched)
    add_c03_travel(bundle, enriched)
    add_c04_pins(bundle, enriched)
    add_c05_endpoints(bundle, enriched)
    add_c07_city_coherence(bundle, enriched)
    add_c08_access(bundle, enriched)
    # R12-H5：C-06 在 C-08 之后——返程到城变量（active_ret_vars）
    # 由 C-08 创建，「返程后才许插一个」依赖它
    add_c06_remote_exclusivity(bundle, enriched, relax=flags.relax_remote_exclusive)

    from .c09_c16 import (
        add_c09_meals,
        add_c10_remote_lunch,
        add_c11_shows,
        add_c12_afternoon_single_big,
        add_c12_family_day,
        add_c12c_morning_single,
        add_c13_hotels,
        add_c14_coverage_before_fill,
        add_c15_remote_departure,
        add_c16_diversity_caps,
    )

    add_c09_meals(bundle, enriched)
    add_c10_remote_lunch(bundle, enriched)
    add_c11_shows(bundle, enriched)
    add_c12_family_day(bundle, enriched)
    add_c12_afternoon_single_big(bundle, enriched)
    add_c12c_morning_single(bundle, enriched)
    add_c13_hotels(bundle, enriched)
    add_c14_coverage_before_fill(bundle, enriched)
    add_c15_remote_departure(bundle, enriched)
    add_c16_diversity_caps(bundle, enriched, relax=flags.relax_diversity)

    from .c17_city_days import add_c17_city_days

    add_c17_city_days(bundle, enriched)
    from .c25_must_days import add_c25_must_days

    add_c25_must_days(bundle, enriched)
    return bundle
