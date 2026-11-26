"""C-09..C-16 constraints and F-22 remote-lunch semantics (P1-D).

Meal and hotel anchors are model intervals, not post-solve patches. A meal's
``host_cid`` is its solution-location anchor; for non-remote hosts the meal is
also temporally nested in that host. Remote meals are different by design:
C-08 exposes the access-arrival/return variables and F-22 chooses either
lunch-at-arrival → visit or visit-at-arrival → lunch, never a city lunch
between the morning anchor and the outbound departure. Remote dinner defaults
to the city and moves to the remote site only when the computed city start
would pass 19:30 (or a real restaurant is explicitly bound to that site).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from app.services.itinerary.rules import (
    SHUTTLE_BOARD_BUFFER_MINUTES,
    TAXI_HAIL_MINUTES,
)
from app.services.itinerary.solver import (
    SHOW_AFTERNOON_START_MINUTES,
    effective_show_sessions,
    is_sessionless_show,
)

from .c01_c04 import closed_weekdays, day_date
from .c05_c08 import DEFAULT_GATEWAY_TAXI_MINUTES, RETURN_BUFFER_MINUTES
from .vars import DAY_END_MINUTES, DAY_START_MINUTES, MINUTES_PER_DAY, VarBundle

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot

MEAL_WINDOWS = {
    "lunch": (11 * 60 + 30, 12 * 60 + 30),
    "dinner": (17 * 60, 19 * 60 + 30),
}
MEAL_DURATIONS = {"lunch": (60, 45, 30), "dinner": (90, 60, 45)}
# R12-H18（2026-11-20 用户拍板「如果景点很大，吃饭时间就在景点时间内
# 时候可以直接被COVER掉。。而不是再安排」）：大点游览段盖住饭点核
# 心（午 12:00-13:00 / 晚 18:00-19:00）⇒ 该槽占位餐卡取消（园内解
# 决），紧凑行程尤其释放墙钟（慕田峪 10:08-13:28 盖午点→午餐被长城
# COVER，13:28 收尾直上 14:30 班）；真餐馆绑定槽（烤鸭卡）不受取消。
MEAL_COVER_CORE = {"lunch": (12 * 60, 13 * 60), "dinner": (18 * 60, 19 * 60)}
REMOTE_LUNCH_EARLIEST = 11 * 60  # Q4
REMOTE_LUNCH_LATEST = 13 * 60  # C-10 arrival band ends at 13:00
REMOTE_DINNER_LATEST = 19 * 60 + 30  # 2026-11-18 用户拍板
DAY_LOAD_BUDGET_MINUTES = 570  # legacy _MUST_DAY_USABLE_MIN
MEAL_TRAVEL_FLOOR = 30  # 铁律 7 地板（rules.travel_gap_needed）
AFTERNOON_START = 13 * 60  # 下午单大点闸（2026-11-04 拍板）
MORNING_END = 12 * 60  # 上午单点闸（2026-11-03 拍板「上午一般只排一个点」）
SIGHT_CAP_PER_DAY = 4
FILL_CAP_PER_DAY = 6
HOTEL_MORNING_READY = 9 * 60
HOTEL_MORNING_MINUTES = 30
HOTEL_NIGHT_DEFAULT_START = 21 * 60
HOTEL_NIGHT_GAP_MINUTES = 30
HOTEL_NIGHT_MINUTES = 60
NON_SIGHT_CATEGORIES = frozenset({"food", "hotel", "entertainment"})
SIGHT_CATEGORIES = frozenset(
    {
        "attraction",
        "museum",
        "park",
        "temple",
        "historic",
        "nature",
        "scenic",
        "sight",
        "garden",
    }
)


def _active_end(model: cp_model.CpModel, name: str, lit, end) -> cp_model.IntVar:
    active = model.NewIntVar(0, MINUTES_PER_DAY + 300, name)
    model.Add(active == end).OnlyEnforceIf(lit)
    model.Add(active == 0).OnlyEnforceIf(lit.Not())
    return active


def _add_same_venue_nesting(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    by_key = {c.cid: c for c in snapshot.candidates}
    by_key.update({c.poi_id: c for c in snapshot.candidates if c.poi_id})
    for guest in snapshot.candidates:
        target_key = getattr(guest, "same_venue", None)
        host = by_key.get(target_key)
        if host is None or host.cid == guest.cid:
            continue
        for day in bundle.days:
            pg = bundle.presence[(guest.cid, day)]
            ph = bundle.presence[(host.cid, day)]
            bundle.model.Add(pg <= ph)
            if (
                guest.category == "food"
                and (host.poi_id or host.cid) in enriched.access_by_poi
            ):
                # Remote real food uses the F-22 solution-location anchor;
                # its lunch/dinner may precede/follow the visit, not nest.
                continue
            bundle.model.Add(
                bundle.start[(guest.cid, day)] >= bundle.start[(host.cid, day)]
            ).OnlyEnforceIf([pg, ph])
            bundle.model.Add(
                bundle.start[(guest.cid, day)] + bundle.dur[guest.cid]
                <= bundle.start[(host.cid, day)] + bundle.dur[host.cid]
            ).OnlyEnforceIf([pg, ph])


def add_c09_meals(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    """Lunch/dinner windows, same-venue nesting and real-food card binding."""
    snapshot = enriched.snapshot
    model = bundle.model
    _add_same_venue_nesting(bundle, enriched)

    # 2026-11-22 闭合行程返程日晚餐抑制：末日有合成返程腿（17:00 傍晚
    # 回城，closed_return_day 统一裁决）——晚餐槽（17:00-19:30）与腿窗
    # 完全重叠，人在回城路上不在这座城吃晚饭（legacy 返程日无晚餐同
    # 口径）。真餐馆绑定槽一并抑制（绑定语义=在这座城吃，回城日不成立）。
    from .c17_city_days import closed_return_day

    _return_day = closed_return_day(
        snapshot.request.cities, snapshot.request.days, snapshot.request.city_days
    )

    for day in bundle.days:
        active = model.NewBoolVar("day_active_%d" % day)
        literals = [bundle.presence[(c.cid, day)] for c in snapshot.candidates]
        if literals:
            model.AddMaxEquality(active, literals)
        else:
            model.Add(active == 0)
        bundle.day_active[day] = active

        remote_lits = [
            bundle.presence[(c.cid, day)]
            for c in snapshot.candidates
            if (c.poi_id or c.cid) in enriched.access_by_poi
        ]
        remote_day = model.NewBoolVar("remote_day_%d" % day)
        if remote_lits:
            model.AddMaxEquality(remote_day, remote_lits)
        else:
            model.Add(remote_day == 0)

        for slot in ("lunch", "dinner"):
            lit = model.NewBoolVar("meal_%s_%d" % (slot, day))
            st = model.NewIntVar(0, MINUTES_PER_DAY, "ms_%s_%d" % (slot, day))
            du = model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(MEAL_DURATIONS[slot]),
                "md_%s_%d" % (slot, day),
            )
            en = model.NewIntVar(0, MINUTES_PER_DAY + 90, "me_%s_%d" % (slot, day))
            model.NewOptionalIntervalVar(st, du, en, lit, "mi_%s_%d" % (slot, day))
            lo, hi = MEAL_WINDOWS[slot]
            # R12: 餐窗约束移至绑定循环之后，按 bound_any 分流（占位守窗/绑定流式）。

            meal = {
                "p": lit,
                "start": st,
                "dur": du,
                "end": en,
                "active_end": _active_end(model, "mae_%s_%d" % (slot, day), lit, en),
                "hosts": {},
                "bound": {},
                "anchor_candidates": [],
                # R12: 占位守窗与绑定真餐馆分流（约束见绑定循环之后）
                "bound_any": model.NewBoolVar("mba_%s_%d" % (slot, day)),
            }
            bundle.meal_vars[(slot, day)] = meal
            if slot == "dinner" and day == _return_day:
                # 返程日晚餐槽灭活（占位与真餐馆绑定一并）：腿窗重叠排除
                model.Add(lit == 0)
            # R12-H18 大点盖饭：游览段盖住饭点核心 ⇒ 占位槽取消；
            # 真餐馆绑定槽（bound_any）不受取消——烤鸭卡照常落午餐/晚餐。
            from ..inputs.hours_caps import BIG_SITE_MIN_MINUTES
            from ..inputs.hours_caps import is_big_site as _is_big

            _cover_lits = []
            for c in snapshot.candidates:
                if (c.category or "") in (
                    "food",
                    "hotel",
                    "transport",
                    "transfer",
                ):
                    continue
                _bvt = (c.best_visit_time or "").lower()
                # R20：夜属性大时长卡同样盖得住饭点核——18:00 开场的夜街把
                # 18-19 晚餐核盖住时取消占位晚餐槽，而不是把晚餐挤到 17:00
                # （R12-H18 大点盖饭语义的夜游扩展；真餐馆绑定槽不受影响）。
                _evening_big = (
                    _bvt in ("evening", "sunset")
                    and (c.suggested_duration_min or 0) > BIG_SITE_MIN_MINUTES
                )
                if (
                    not _is_big(
                        duration_min=c.suggested_duration_min,
                        category=c.category,
                        best_visit_time=c.best_visit_time,
                        tier=c.tier,
                        pinned_with_time=False,
                    )
                    and not _evening_big
                ):
                    continue
                _cl = model.NewBoolVar("mcover_%s_%s_%d" % (slot, c.cid, day))
                _p = bundle.presence[(c.cid, day)]
                # 未在场卡不得 COVER（否则弃排卡白送覆盖、误杀餐锚）
                model.Add(_cl == 0).OnlyEnforceIf(_p.Not())
                _lo, _hi = MEAL_COVER_CORE.get(slot, (0, 0))
                model.Add(bundle.start[(c.cid, day)] <= _lo).OnlyEnforceIf([_p, _cl])
                model.Add(
                    bundle.start[(c.cid, day)] + bundle.dur[c.cid] >= _hi
                ).OnlyEnforceIf([_p, _cl])
                _late = model.NewBoolVar("mcovlate_%s_%s_%d" % (slot, c.cid, day))
                model.Add(bundle.start[(c.cid, day)] > _lo).OnlyEnforceIf(
                    [_p, _cl.Not(), _late]
                )
                model.Add(
                    bundle.start[(c.cid, day)] + bundle.dur[c.cid] < _hi
                ).OnlyEnforceIf([_p, _cl.Not(), _late.Not()])
                _cover_lits.append(_cl)
            covered = model.NewBoolVar("meal_covered_%s_%d" % (slot, day))
            meal["covered"] = covered
            if _cover_lits:
                model.AddMaxEquality(covered, _cover_lits)
            else:
                model.Add(covered == 0)
            model.Add(lit == 0).OnlyEnforceIf([covered, meal["bound_any"].Not()])
            model.Add(lit == active).OnlyEnforceIf([covered.Not(), meal["bound_any"]])
            model.Add(lit == active).OnlyEnforceIf([covered, meal["bound_any"]])
            model.Add(lit == active).OnlyEnforceIf(
                [covered.Not(), meal["bound_any"].Not()]
            )

            for cand in snapshot.candidates:
                p_cand = bundle.presence[(cand.cid, day)]
                c_start = bundle.start[(cand.cid, day)]
                c_end = c_start + bundle.dur[cand.cid]
                profiled = (cand.poi_id or cand.cid) in enriched.access_by_poi
                slot_val = getattr(cand, "meal_slot", None)
                bound_lit = None
                if cand.category == "food" and slot_val == slot:
                    bound_lit = p_cand
                elif cand.category == "food" and slot_val == "any":
                    # R8-S2b 餐类必去（legacy 同口径：不锁槽）：真餐厅
                    # 自选午/晚槽——每个放置日恰绑一个槽（两槽选择
                    # 布尔之和 == presence）；未绑的另一槽照常出系统
                    # 餐卡（不双餐）。
                    bound_lit = bundle.meal_bound.setdefault(
                        (cand.cid, day, slot),
                        model.NewBoolVar("mb_%s_%d_%s" % (cand.cid, day, slot)),
                    )
                    mate = "dinner" if slot == "lunch" else "lunch"
                    mate_lit = bundle.meal_bound.setdefault(
                        (cand.cid, day, mate),
                        model.NewBoolVar("mb_%s_%d_%s" % (cand.cid, day, mate)),
                    )
                    model.Add(bound_lit + mate_lit == p_cand)

                if bound_lit is not None:
                    # The system card is the slot; the real restaurant fills
                    # its data. Once selected, the binding cannot drift.
                    model.Add(st == c_start).OnlyEnforceIf(bound_lit)
                    model.Add(du == bundle.dur[cand.cid]).OnlyEnforceIf(bound_lit)
                    # R12（2026-11-19 拍板「烤鸭店算景点，不是一定 11:30」）：绑定真
                    # 餐馆不再餐窗硬钳——时刻=营业时间（C-02）+C-03 走行缝+C-01 不重
                    # 叠的流式解，直排前一景之后（此前仅远程 F-22 绑定豁免午餐钳）。
                    meal["bound"][cand.cid] = bound_lit
                    continue

                if profiled:
                    continue  # F-22 owns both remote meal orderings

                host = model.NewBoolVar("mh_%s_%s_%d" % (slot, cand.cid, day))
                meal["hosts"][cand.cid] = host
                model.Add(host <= p_cand)
                model.Add(host <= lit)
                if (
                    cand.category in ("food", "hotel", "entertainment")
                    or (cand.best_visit_time or "").lower() == "show"
                ):
                    model.Add(host == 0)  # blocker cards never host a meal
                model.Add(st >= c_start).OnlyEnforceIf(host)
                model.Add(en <= c_end).OnlyEnforceIf(host)

                order = model.NewBoolVar("mo_%s_%s_%d" % (slot, cand.cid, day))
                # 铁律 7 餐侧（P2-B3 iter2）：餐卡按宿主坐标参与走行
                # 缝——地板 30；宿主嵌套（host）与远郊 F-22 豁免
                model.Add(en + MEAL_TRAVEL_FLOOR <= c_start).OnlyEnforceIf(
                    [p_cand, host.Not(), order]
                )
                model.Add(st >= c_end + MEAL_TRAVEL_FLOOR).OnlyEnforceIf(
                    [p_cand, host.Not(), order.Not()]
                )

            if meal["hosts"]:
                model.Add(sum(meal["hosts"].values()) <= 1)

            # R12 流式餐卡（2026-11-19 用户拍板「烤鸭店算景点，不是一定
            # 11:30；天安门后应该在去下一个景点的路上，不空等午餐卡」）：
            # 餐窗只继续约束系统占位餐卡；绑定真餐馆（bound_any）时刻=
            # 营业时间（C-02 hours_caps）+ C-03 走行缝 + C-01 不重叠的
            # 流式解——直排前一景之后，不再受 [lo, hi] 硬钳。远程日午餐
            # 仍保 11:00 到达地板（F-22 嵌套语义不变）。
            if meal["bound"]:
                model.AddMaxEquality(meal["bound_any"], list(meal["bound"].values()))
            else:
                model.Add(meal["bound_any"] == 0)
            if slot == "lunch":
                model.Add(st >= REMOTE_LUNCH_EARLIEST).OnlyEnforceIf(remote_day)
                model.Add(st >= lo).OnlyEnforceIf(
                    [remote_day.Not(), meal["bound_any"].Not()]
                )
                model.Add(st <= hi).OnlyEnforceIf(
                    [remote_day.Not(), meal["bound_any"].Not()]
                )
            else:
                model.Add(st >= lo).OnlyEnforceIf([lit, meal["bound_any"].Not()])
                model.Add(st <= hi).OnlyEnforceIf([lit, meal["bound_any"].Not()])

            # A real same-venue restaurant determines both the system card and
            # its location anchor. This also covers palace same-site rulings.
            for guest in snapshot.candidates:
                if (
                    guest.category != "food"
                    or getattr(guest, "meal_slot", None) != slot
                ):
                    continue
                host_key = getattr(guest, "same_venue", None)
                host_cand = next(
                    (
                        c
                        for c in snapshot.candidates
                        if c.cid == host_key or (c.poi_id and c.poi_id == host_key)
                    ),
                    None,
                )
                if host_cand is None:
                    continue
                host_lit = meal["hosts"].get(host_cand.cid)
                if host_lit is not None:
                    model.Add(host_lit == 1).OnlyEnforceIf(
                        bundle.presence[(guest.cid, day)]
                    )

    # R12-D3：池内餐馆硬闸（同菜系同日≤1 + 槽位时段对齐；必去豁免）
    _r12d_hard_gates(bundle, enriched)
    # R13h：同站孪生互斥（legacy _same_visit 通道族移植）——多源同行
    # 跨天双卡防线（朱家角同地名行/同票家族/大小兄弟/演出桶/联票挂牌）；
    # 博物馆×伞形组合对豁免连排（11-07 终裁）与全部地理闸见 inputs/twins。
    _r13h_twin_exclusivity(bundle, enriched)
    # R12-F4b：填充日预算（因果版——必去满档计，压缩不产预算）
    _r12f_fill_yields_gate(bundle, enriched)
    # R12-H：收缩晚带闸（14:00 前满档，压到档低不够就按规则弃点）
    _r12h_shrink_band_gate(bundle, enriched)


def _r12h_shrink_band_gate(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    """R12-H3（2026-11-20 用户拍板「压缩只发生在晚上、晚闸 16:30 前
    的景点上；超过规定的压缩值还不满足就开始按规则删景点」+纠正
    「你不要规定开场时间」+「同样的PRIORITY 并且天气允许，先安排
    远郊。远郊优先安排早晨 & 单天只有空闲才插入其它」）：时长收缩
    只允许**收尾越过 min(晚闸16:30, 自家窗闭) 的卡**——晚带收尾
    （颐和园 15:02-18:56 压 31 分收口 ✓）或贴自家闭馆墙（窗逼缩=
    被迫合法 ✓）；故宫 13:54-14:54 收在闸前 ✗ 不许缩。钉住卡豁免
    （铁律19：钉造成的收缩是用户自己的选择）；餐宿交通类豁免。压
    到档低仍不满足 → tier① 覆盖按规则弃点：填充先让位（F4b 预算）、
    必去诚实降「想去」+披露。远郊四条：同优先级（覆盖权重/晚开罚
    通用）+天气允许先排远郊（日序拉引，雨天硬闸限可行面）+远郊优
    先早晨（开场拉引+出程下限 08:30）+单天只空闲才插其它（F4b 日
    预算）——拉引项在 objectives._remote_first。
    """
    model = bundle.model
    evening_gate = 16 * 60 + 30
    request = enriched.snapshot.request
    pinned = {
        c.cid
        for pin in (getattr(request, "pins", ()) or ())
        for c in enriched.snapshot.candidates
        if pin.rid == c.rid or (pin.cid and pin.cid == c.cid)
    }
    for c in enriched.snapshot.candidates:
        if (c.category or "") in (
            "food",
            "hotel",
            "transport",
            "transfer",
        ):
            continue
        if c.cid in pinned:
            continue  # 铁律19：钉造成的收缩是用户自己的选择
        tier = enriched.tiers[c.cid]
        if tier[1] <= tier[0]:
            continue  # 无压缩空间（typ==min）
        window = enriched.windows.get(c.cid)
        gate = evening_gate if window is None else min(evening_gate, window[1])
        shrunk = model.NewBoolVar("sbg_%s" % c.cid)
        model.Add(bundle.dur[c.cid] < tier[1]).OnlyEnforceIf(shrunk)
        model.Add(bundle.dur[c.cid] >= tier[1]).OnlyEnforceIf(shrunk.Not())
        for day in bundle.days:
            present = bundle.presence[(c.cid, day)]
            # 收缩 ⇒ 收尾越过 min(晚闸, 窗闭)——晚带收尾/贴自家闭馆墙（合法）
            model.Add(
                bundle.start[(c.cid, day)] + bundle.dur[c.cid] >= gate
            ).OnlyEnforceIf([shrunk, present])


def _r12f_fill_yields_gate(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    """R12-F4b（2026-11-19 用户纠正「不是该天填充一律不得在场，而是
    引起收缩的填充不应插入」）：因果编码=日预算——必去按**满档 mid**
    计入预算（压缩不产生填充预算：为容填充而缩在预算上不可能），填充
    只能消费真余量；必去自挤溢出日（满档+骨架超容）豁免预算——必去
    自己缩合法（傍晚收口闸/窄窗自缩与填充无关，无辜填充照常进场）。
    填充可选，永不致不可行。

    R39（2026-11-25 用户「why no restaurants is picked up at all」）：餐馆
    不占填充预算。餐位时刻已在 skeleton 的 150 分钟里预留，餐馆只是填进
    这张已留的餐卡（C-09 bound/anchor），不是额外塞进景点行程的填充卡；
    把它计进 fill_mid 等于同一份时间算两次。稠密日（12 必去/4 天）必去
    满档吃掉整个预算后，7 家库内高分餐馆全被本闸压掉、餐卡全落成自由卡
    ——与「按评分+地理选餐厅」的 R29 初衷相悖。餐馆另受 R12-D3（同菜系
    同日≤1、槽位时段对齐）与 _meal_near_gate（就近硬闸）约束，不因豁免本
    预算而失控；R29 前只有 4 条 pois 荐点行受影响，行为等价。
    """
    model = bundle.model
    cands = enriched.snapshot.candidates
    reqs = [c for c in cands if c.rid]
    # 餐馆=餐卡数据源，不是景点填充：不进 fill_mid 预算（R39）。
    fills = [c for c in cands if not c.rid and (c.category or "") != "food"]
    if not reqs or not fills:
        return
    capacity = DAY_END_MINUTES - DAY_START_MINUTES  # 750
    skeleton = 240  # 午+晚餐满档 150 + 晨/夜酒店锚 90
    gap = 30  # 邻卡走行地板/卡
    remote_chain = 200  # 远郊接驳链（去+回）占的日时间
    for day in bundle.days:
        must_mid = model.NewIntVar(0, 10000, "fbm_%d" % day)
        model.Add(
            must_mid
            == sum(
                (enriched.tiers[c.cid][1] + gap) * bundle.presence[(c.cid, day)]
                for c in reqs
            )
        )
        base = skeleton
        remote_lits = [bundle.presence[(c.cid, day)] for c in cands if c.remote]
        if remote_lits:
            remote_lit = model.NewBoolVar("fbr_%d" % day)
            model.AddMaxEquality(remote_lit, remote_lits)
            base = base + remote_chain * remote_lit
        # 溢出=必去满档自挤（+骨架）超容：豁免预算（必去自己缩）
        overflow = model.NewBoolVar("fbo_%d" % day)
        model.Add(must_mid + base >= capacity + 1).OnlyEnforceIf(overflow)
        model.Add(must_mid + base <= capacity).OnlyEnforceIf(overflow.Not())
        fill_mid = model.NewIntVar(0, 10000, "fbf_%d" % day)
        model.Add(
            fill_mid
            == sum(
                (enriched.tiers[f.cid][1] + gap) * bundle.presence[(f.cid, day)]
                for f in fills
            )
        )
        # 预算：必去满档 + 骨架 + 填充 ≤ 日容（溢出日豁免）
        model.Add(must_mid + base + fill_mid <= capacity).OnlyEnforceIf(overflow.Not())


def _r13h_twin_exclusivity(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    """R13h（2026-11-20 深挖）：同站孪生一次行程只看一次——孪生对
    （inputs/twins.twin_gate_km 通道判定）在场总和 ≤1（跨天也并；大足
    day5/day6 双卡即此类）。地理闸同 legacy：双方有坐标且越闸=名字撞衫
    的不同场馆不并；缺坐标维持名字判定。必去×必去孪生（用户点名两个
    名字同一站）也并——与「北山+宝顶也要并」拍板同语义。
    """
    from ..inputs.travel import haversine_km
    from ..inputs.twins import combo_same_day, twin_gate_km

    cands = enriched.snapshot.candidates
    days = bundle.days
    for i, a in enumerate(cands):
        for b in cands[i + 1 :]:
            gate = twin_gate_km(a, b)
            if gate is not None and gate > 0:
                if a.lon is not None and b.lon is not None:
                    if haversine_km(a.lon, a.lat, b.lon, b.lat) > gate:
                        gate = None  # 名字撞衫的不同场馆（泛名山岳保护闸）
            if gate is not None:
                pair_lits = [
                    bundle.presence[(a.cid, d)] + bundle.presence[(b.cid, d)]
                    for d in days
                ]
                if pair_lits:
                    bundle.model.Add(sum(pair_lits) <= 1)
                continue
            # 11-07 终裁组合对：两卡并存但**双在场⇒同日**（连排成组）。
            if not combo_same_day(a, b):
                continue
            if (
                a.lon is not None
                and b.lon is not None
                and haversine_km(a.lon, a.lat, b.lon, b.lat) > 2.5
            ):
                continue
            for d in days:
                for e in days:
                    if d == e:
                        continue
                    bundle.model.Add(
                        bundle.presence[(a.cid, d)] + bundle.presence[(b.cid, e)] <= 1
                    )


#: R41 餐馆就近闸半径 km（原 objectives.MEAL_NEAR_SIGHT_KM 同值同义，随闸
#: 迁到唯一消费点）。与选池侧 meal_geo.MEAL_GEO_CLUSTER_KM 同口径。
MEAL_NEAR_SIGHT_KM = 2.5


#: R41 绑定正餐的时段窗：午餐不早于 11:00（REMOTE_LUNCH_EARLIEST 同值）、
#: 晚餐不早于 17:00（系统占位餐卡 MEAL_WINDOWS["dinner"] 起点同值）。旧闸只卡
#: 15:00 午/晚分界，绑定餐没有时段窗——大预算/打磨解里出过 09:00 的「午餐」、
#: 15:30 的「晚餐」（读路径按时刻又判成早餐/下午茶，再补一张自由卡）。
MEAL_LUNCH_EARLIEST = 11 * 60
MEAL_DINNER_EARLIEST = 17 * 60


def _meal_near_gate(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    """R41：自动选餐的**餐馆侧就近硬闸**（取代 R29 的 400 软罚）。

    非用户点名（rid 空）的餐候选落在某天 ⇒ 当天必须有 MEAL_NEAR_SIGHT_KM 内
    的池内景点在场；2.5km 内根本没有池内景点的候选 = 离哪天的动线都远，直接
    全程不可选（宁缺勿错，不再出现「长城日晚餐落 54km 外市区店」）。

    为什么可以硬化（R29 当年不敢）：闸只约束餐馆一侧、绝不强迫任何景点在场
    ——「所有餐候选全程不在场」永远可行（占位餐卡兜底），不会像旧写法那样
    牵连景点把搜索压成「只剩必去」。同时它把 R29 软罚造成的「分日 × 落餐」
    目标耦合从 preference 层拿掉：餐馆的可行天集合由景点分日直接传播，搜索
    空间随之缩小。用户点名的餐馆（rid）不受限（显式选择优先，同 R29）。
    """
    from ..inputs.travel import haversine_km

    snapshot = enriched.snapshot
    model = bundle.model
    sights = [
        c
        for c in snapshot.candidates
        if (c.category or "") not in ("food", "hotel", "transport", "transfer")
        and not getattr(c, "meal_slot", None)
        and getattr(c, "lon", None) is not None
        and getattr(c, "lat", None) is not None
    ]
    for cand in snapshot.candidates:
        if (cand.category or "") != "food" or not getattr(cand, "meal_slot", None):
            continue
        if cand.rid:  # 用户点名的餐馆＝用户选择，不做就近约束
            continue
        lon = getattr(cand, "lon", None)
        lat = getattr(cand, "lat", None)
        if lon is None or lat is None:  # 无坐标（或精简桩）：无从判就近，不加闸
            continue
        near = [
            s
            for s in sights
            if haversine_km(lon, lat, s.lon, s.lat) <= MEAL_NEAR_SIGHT_KM
        ]
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            if not near:
                model.Add(lit == 0)
                continue
            model.AddBoolOr([lit.Not()] + [bundle.presence[(s.cid, day)] for s in near])


def _r12d_hard_gates(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    """R12-D3（2026-11-19 拍板「选餐点：尽量不要同样的菜肴」）：池内
    自动选的餐馆（fill、无 rid）两道硬闸——用户必去（rid）不受限（显式
    选择优先）。

    ① 同菜系两店同日至多一家在场（any-槽：在场⇔绑定——同日双绑即双在
       场，presence 和 ≤1 一式即闸）；
    ② 槽位时段对齐：午槽绑定 ⇒ 11:00≤时刻<15:00、晚槽绑定 ⇒ ≥17:00
       （倒挂直接不可行——槽标签跟时刻走，不再受 tier_det 搜索预算摆布；
       R41 补正餐时段窗：09:00 的「午餐」/15:30 的「晚餐」同样不可行；
       软罚/软奖励继续服务必去餐馆与跨天去重）。占位餐卡永远可兜底，
       各闸均不会造成不可行。
    """
    model = bundle.model
    split = 15 * 60
    fill_foods = [
        c
        for c in enriched.snapshot.candidates
        if (c.category or "") == "food" and not c.rid and getattr(c, "cuisine", None)
    ]
    # R29：槽位时段闸（午槽<15:00 / 晚槽≥15:00）不依赖菜系键——两表新候选里
    # 菜系识别不出的行（北京菜/酒店餐厅名）此前整条绕过闸，出过 17:37 落
    # lunch 卡的倒挂；闸只禁错标，不损覆盖（占位卡永远兜底）。
    bound_foods = [
        c
        for c in enriched.snapshot.candidates
        if (c.category or "") == "food" and not c.rid and getattr(c, "meal_slot", None)
    ]
    for day in bundle.days:
        for i, c1 in enumerate(fill_foods):
            for c2 in fill_foods[i + 1 :]:
                if c1.cuisine != c2.cuisine:
                    continue
                model.Add(
                    bundle.presence[(c1.cid, day)] + bundle.presence[(c2.cid, day)] <= 1
                )
        for c in bound_foods:
            ms = getattr(c, "meal_slot", None)
            for slot in ("lunch", "dinner"):
                if ms == slot:
                    blit = bundle.presence[(c.cid, day)]
                elif ms == "any":
                    blit = bundle.meal_bound.get((c.cid, day, slot))
                else:
                    blit = None
                if blit is None:
                    continue
                if slot == "lunch":
                    model.Add(bundle.start[(c.cid, day)] < split).OnlyEnforceIf(blit)
                    # R41：午餐不得落在早餐时段（≥11:00，≤15:00 由上式保证）
                    model.Add(
                        bundle.start[(c.cid, day)] >= MEAL_LUNCH_EARLIEST
                    ).OnlyEnforceIf(blit)
                else:
                    # R41：晚餐 ≥17:00（旧版 ≥15:00 会把下午茶时段标成晚餐）
                    model.Add(
                        bundle.start[(c.cid, day)] >= MEAL_DINNER_EARLIEST
                    ).OnlyEnforceIf(blit)
    # R41 ③：餐馆侧就近硬闸（原 R29 objectives._meal_far_penalty 软罚的硬化）
    _meal_near_gate(bundle, enriched)


def add_c10_remote_lunch(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    """F-22 remote meals: lunch before/after visit; dinner by the 19:30 gate."""
    snapshot = enriched.snapshot
    model = bundle.model
    for cand in snapshot.candidates:
        if (cand.poi_id or cand.cid) not in enriched.access_by_poi:
            continue
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            arrival = bundle.arrival_vars.get((cand.cid, day))
            lunch = bundle.meal_vars.get(("lunch", day))
            if arrival is None or lunch is None:
                continue
            lunch["anchor_candidates"].append((cand.cid, lit))
            before = model.NewBoolVar("rlb_%s_%d" % (cand.cid, day))
            early = model.NewBoolVar("rle_%s_%d" % (cand.cid, day))
            late = model.NewBoolVar("rll_%s_%d" % (cand.cid, day))
            model.Add(before == 0).OnlyEnforceIf(lit.Not())
            model.Add(arrival < REMOTE_LUNCH_EARLIEST).OnlyEnforceIf([lit, early])
            model.Add(arrival >= REMOTE_LUNCH_EARLIEST).OnlyEnforceIf(
                [lit, early.Not()]
            )
            model.Add(arrival > REMOTE_LUNCH_LATEST).OnlyEnforceIf([lit, late])
            model.Add(arrival <= REMOTE_LUNCH_LATEST).OnlyEnforceIf([lit, late.Not()])
            model.Add(before == 0).OnlyEnforceIf([lit, early])
            model.Add(before == 0).OnlyEnforceIf([lit, late])
            model.Add(before == 1).OnlyEnforceIf([lit, early.Not(), late.Not()])

            # R12-H18：远郊日午餐被大点盖住（如长城 10:08-13:28 盖午
            # 点）⇒ 允许取消——强制锚会让早班形状不可行、班车漂移。
            model.Add(lunch["p"] == 1).OnlyEnforceIf([lit, lunch["covered"].Not()])
            model.Add(before == 0).OnlyEnforceIf([lit, lunch["covered"]])
            model.Add(lunch["start"] == arrival).OnlyEnforceIf([lit, before])
            model.Add(bundle.start[(cand.cid, day)] == lunch["end"]).OnlyEnforceIf(
                [lit, before]
            )
            model.Add(bundle.start[(cand.cid, day)] == arrival).OnlyEnforceIf(
                [lit, before.Not()]
            )
            model.Add(
                lunch["start"] >= bundle.start[(cand.cid, day)] + bundle.dur[cand.cid]
            ).OnlyEnforceIf([lit, before.Not()])

            ret = bundle.ret_vars.get((cand.cid, day))
            dinner = bundle.meal_vars[("dinner", day)]
            if ret is None:
                # No return timetable: dinner may precede or follow the visit,
                # but it may never overlap it (review finding 3).
                after_visit = model.NewBoolVar("rdn_%s_%d" % (cand.cid, day))
                model.Add(dinner["end"] <= bundle.start[(cand.cid, day)]).OnlyEnforceIf(
                    [lit, after_visit]
                )
                model.Add(
                    dinner["start"]
                    >= bundle.start[(cand.cid, day)] + bundle.dur[cand.cid]
                ).OnlyEnforceIf([lit, after_visit.Not()])
                dinner["anchor_candidates"].append((cand.cid, lit))
                continue
            # Post-visit lunch is still at the site: the return shuttle
            # cannot leave while that lunch is in progress.
            model.Add(ret >= lunch["end"] + RETURN_BUFFER_MINUTES).OnlyEnforceIf(
                [lit, before.Not()]
            )
            profile = enriched.access_by_poi[cand.poi_id or cand.cid]
            return_arrival = ret + profile.ride_minutes + profile.last_mile_minutes
            late_city_dinner = model.NewBoolVar("rdl_%s_%d" % (cand.cid, day))
            remote_dinner = model.NewBoolVar("rd_%s_%d" % (cand.cid, day))
            model.Add(late_city_dinner <= lit)
            model.Add(remote_dinner == 0).OnlyEnforceIf(lit.Not())
            model.Add(return_arrival > REMOTE_DINNER_LATEST).OnlyEnforceIf(
                [lit, late_city_dinner]
            )
            model.Add(return_arrival <= REMOTE_DINNER_LATEST).OnlyEnforceIf(
                [lit, late_city_dinner.Not()]
            )
            explicit_remote_food = [
                bundle.presence[(food.cid, day)]
                for food in snapshot.candidates
                if food.category == "food"
                and getattr(food, "meal_slot", None) == "dinner"
                and getattr(food, "same_venue", None) in (cand.cid, cand.poi_id)
            ]
            model.AddMaxEquality(
                remote_dinner, [late_city_dinner, *explicit_remote_food]
            )
            dinner["anchor_candidates"].append((cand.cid, remote_dinner))
            # Default: dinner back in the city by 19:30. Only a later
            # computed arrival (or an explicit remote restaurant) permits
            # dinner at the remote site; its return then follows dinner.
            model.Add(dinner["start"] >= return_arrival).OnlyEnforceIf(
                [lit, remote_dinner.Not()]
            )
            model.Add(
                dinner["start"] >= bundle.start[(cand.cid, day)] + bundle.dur[cand.cid]
            ).OnlyEnforceIf([lit, remote_dinner])
            model.Add(ret >= dinner["end"] + RETURN_BUFFER_MINUTES).OnlyEnforceIf(
                [lit, remote_dinner]
            )


def _show_off_season(hours_text: str | None, months: set[int]) -> bool:
    """Legacy _show_off_season semantics without importing agent.plan."""
    hours = str(hours_text or "")
    if not hours or not months:
        return False
    match = re.search(r"演出季\s*(\d{1,2})\s*[-–—~至]\s*(\d{1,2})\s*月", hours)
    if match:
        x, y = int(match.group(1)), int(match.group(2))
        if 1 <= x <= 12 and 1 <= y <= 12:
            return not any(
                (x <= month <= y) if x <= y else (month >= x or month <= y)
                for month in months
            )
        return False
    return "冬季停演" in hours and all(month in (12, 1, 2) for month in months)


def add_c11_shows(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    shows = [
        c
        for c in enriched.snapshot.candidates
        if (c.best_visit_time or "").lower() == "show"
    ]
    months = {
        day_dt.month
        for day in bundle.days
        if (day_dt := day_date(enriched.snapshot.request.start_date, day)) is not None
    }
    for cand in shows:
        sessions = effective_show_sessions(cand.best_visit_time, cand.opening_hours)
        sessionless = is_sessionless_show(cand.best_visit_time, cand.opening_hours)
        off_season = _show_off_season(cand.opening_hours, months)
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            start = bundle.start[(cand.cid, day)]
            if off_season:
                # 冬季停演/演出季外=真不可演 → 禁排（legacy 同口径）。
                bundle.model.Add(lit == 0)
            elif sessions:
                bundle.model.AddAllowedAssignments(
                    [bundle.start[(cand.cid, day)]], [(s,) for s in sessions]
                ).OnlyEnforceIf(lit)
            elif sessionless:
                # R22（2026-11-23 挂账清账）：无场次 SHOW 引擎此前整卡禁排
                # （lit==0，b4f3411 初版移植把 2026-11-14「重排提案层撤下」
                # 错并进 2026-11-11 放置层）——必去组合直接 INFEASIBLE 整单
                # 回落 legacy（合成探针实锤：必去被丢且伪 reason
                # 「day_capacity_conflict」）。对齐 11-11 拍板「无场次 SHOW 下午或
                # 晚上」（legacy solver._visit_spec 同口径 lo=max(lo,
                # SHOW_AFTERNOON_START_MINUTES)）：放置域自中午起开，偏好层
                # SHOW_EARLY_PENALTY 自然压 ≥15:00。
                bundle.model.Add(start >= SHOW_AFTERNOON_START_MINUTES).OnlyEnforceIf(
                    lit
                )
    for day in bundle.days:
        if shows:
            bundle.model.Add(sum(bundle.presence[(c.cid, day)] for c in shows) <= 1)


def add_c12_family_day(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    must_rids = {r.rid for r in snapshot.request.musts}
    families: dict[str, list[str]] = {}
    for cand in snapshot.candidates:
        family = getattr(cand, "family_id", None)
        if family and cand.rid in must_rids:
            families.setdefault(family, []).append(cand.cid)
    for members in families.values():
        for day in bundle.days:
            first = bundle.presence[(members[0], day)]
            for cid in members[1:]:
                bundle.model.Add(bundle.presence[(cid, day)] == first)

    budget = int(
        getattr(snapshot.request, "day_load_budget_min", DAY_LOAD_BUDGET_MINUTES)
    )
    for day in bundle.days:
        load = [
            bundle.active_dur[(c.cid, day)]
            for c in snapshot.candidates
            if c.category not in NON_SIGHT_CATEGORIES
        ]
        if load:
            bundle.model.Add(sum(load) <= budget)

        day_dt = day_date(snapshot.request.start_date, day)
        if day_dt is not None:
            iso = day_dt.isoformat()
            for cand in snapshot.candidates:
                weather = enriched.weather.get((cand.cid, iso))
                if weather and weather.get("forbid"):
                    bundle.model.Add(bundle.presence[(cand.cid, day)] == 0)


def _is_pinned(snapshot, cand, day: int) -> bool:
    return any(
        pin.day == day and (pin.rid == cand.rid or (pin.cid and pin.cid == cand.cid))
        for pin in (getattr(snapshot.request, "pins", ()) or ())
    )


def add_c12_afternoon_single_big(
    bundle: VarBundle, enriched: "EnrichedSnapshot"
) -> None:
    """审计「下午单大点」（2026-11-04 拍板）：同日 ≥13:00 开场的
    大点 ≤1。口径同 rules._check_day_mix：>80 分钟非街区/餐/酒店/
    演出类；钉住件豁免（铁律 19）。"""
    from ..inputs.hours_caps import is_big_site

    snapshot = enriched.snapshot
    for day in bundle.days:
        terms = []
        for cand in snapshot.candidates:
            tier = enriched.tiers[cand.cid]
            if not is_big_site(
                duration_min=tier[1],
                category=cand.category,
                best_visit_time=cand.best_visit_time,
                tier=cand.tier,
                pinned_with_time=_is_pinned(snapshot, cand, day),
            ):
                continue
            lit = bundle.presence[(cand.cid, day)]
            ge = bundle.model.NewBoolVar("pm_big_%s_%d" % (cand.cid, day))
            bundle.model.Add(ge == 0).OnlyEnforceIf(lit.Not())
            bundle.model.Add(
                bundle.start[(cand.cid, day)] >= AFTERNOON_START
            ).OnlyEnforceIf([lit, ge])
            bundle.model.Add(
                bundle.start[(cand.cid, day)] < AFTERNOON_START
            ).OnlyEnforceIf([lit, ge.Not()])
            terms.append(ge)
        if len(terms) > 2:
            # R5: 硬闸放宽到 ≤2（拍板原文「一般下午只放一个大点」=软偏好；
            # 打分器下午超点 −12/个 vs 拆簇 −60——硬 ≤1 把 3 大点簇
            # 逼成跨日拆簇）；≤1 的偏好由 tier② 镜像项持有
            bundle.model.Add(sum(terms) <= 2)


def add_c12c_morning_single(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    """上午单点（2026-11-03 拍板）：每活动日 <12:00 开场的非钉观光 ≤1。
    口径同 scorer.morning_crowd（钉件豁免，铁律 19）。
    """
    snapshot = enriched.snapshot
    for day in bundle.days:
        terms = []
        for cand in snapshot.candidates:
            if (cand.category or "") in ("food", "hotel", "transport"):
                continue  # 餐/酒店/接驳不占上午点位
            if _is_pinned(snapshot, cand, day):
                continue  # 铁律 19：用户钉件不计
            if (cand.best_visit_time or "") == "sunrise":
                continue  # R12-H11：晨锁带升旗锚（06:30-08:30）不计
                # 上午单点点位——升旗后同日上午照排正式观光点
            lit = bundle.presence[(cand.cid, day)]
            ge = bundle.model.NewBoolVar("am_%s_%d" % (cand.cid, day))
            bundle.model.Add(ge == 0).OnlyEnforceIf(lit.Not())
            bundle.model.Add(bundle.start[(cand.cid, day)] < MORNING_END).OnlyEnforceIf(
                [lit, ge]
            )
            bundle.model.Add(
                bundle.start[(cand.cid, day)] >= MORNING_END
            ).OnlyEnforceIf([lit, ge.Not()])
            terms.append(ge)
        if len(terms) > 1:
            bundle.model.Add(sum(terms) <= 1)


def add_c13_hotels(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    if not getattr(enriched.snapshot.request, "hotel_anchors", True):
        return
    snapshot = enriched.snapshot
    model = bundle.model
    for day in bundle.days:
        active = bundle.day_active[day]
        adjusted = []
        for cand in snapshot.candidates:
            lit = bundle.presence[(cand.cid, day)]
            profile = enriched.access_by_poi.get(cand.poi_id or cand.cid)
            if profile is not None:
                dep = bundle.dep_vars[(cand.cid, day)]
                # R16：离店最晚=班次−(车程+叫车 15+强约束缓冲 15)——
                # 打车接硬班次的强约束口径（2026-11-21 用户拍板）。
                taxi = (
                    int(profile.taxi_minutes or DEFAULT_GATEWAY_TAXI_MINUTES)
                    + TAXI_HAIL_MINUTES
                    + SHUTTLE_BOARD_BUFFER_MINUTES
                )
                ready = model.NewIntVar(
                    0, MINUTES_PER_DAY, "hr_%s_%d" % (cand.cid, day)
                )
                model.Add(ready == dep - taxi).OnlyEnforceIf(lit)
                model.Add(ready == 0).OnlyEnforceIf(lit.Not())
            else:
                ready = bundle.start[(cand.cid, day)]
                # R12-H21（2026-11-20）：晨锁带卡（升旗类，库内 bvt=
                # 'sunrise'）豁免 09:00 酒店晨锚地板——钉件同款豁免语义
                # （钉测可过正是靠 _is_pinned 豁免；无钉 sunrise 卡撞死）。
                if (
                    not _is_pinned(snapshot, cand, day)
                    and (cand.best_visit_time or "") != "sunrise"
                    and not (day == 1 and snapshot.request.day1_start)
                ):
                    model.Add(ready >= HOTEL_MORNING_READY).OnlyEnforceIf(lit)

            early = model.NewBoolVar("he_%s_%d" % (cand.cid, day))
            model.Add(early <= lit)
            model.Add(ready < HOTEL_MORNING_READY).OnlyEnforceIf([lit, early])
            model.Add(ready >= HOTEL_MORNING_READY).OnlyEnforceIf([lit, early.Not()])
            adjusted_var = model.NewIntVar(
                0, MINUTES_PER_DAY, "ha_%s_%d" % (cand.cid, day)
            )
            model.Add(adjusted_var == ready - HOTEL_MORNING_MINUTES).OnlyEnforceIf(
                [lit, early]
            )
            model.Add(adjusted_var == MINUTES_PER_DAY).OnlyEnforceIf([lit, early.Not()])
            model.Add(adjusted_var == MINUTES_PER_DAY).OnlyEnforceIf(lit.Not())
            adjusted.append(adjusted_var)

        morning_end = model.NewIntVar(0, MINUTES_PER_DAY, "hme_%d" % day)
        morning_start = model.NewIntVar(0, MINUTES_PER_DAY, "hms_%d" % day)
        model.AddMinEquality(morning_end, [HOTEL_MORNING_READY, *adjusted])
        model.Add(morning_start + HOTEL_MORNING_MINUTES == morning_end)
        bundle.hotel_vars[("morning", day)] = {
            "p": active,
            "start": morning_start,
            "end": morning_end,
        }

        night_start = model.NewIntVar(0, MINUTES_PER_DAY + 300, "hns_%d" % day)
        ends = [HOTEL_NIGHT_DEFAULT_START]
        ends.extend(
            bundle.active_end[(c.cid, day)] + HOTEL_NIGHT_GAP_MINUTES
            for c in snapshot.candidates
        )
        ends.extend(
            meal["active_end"] + HOTEL_NIGHT_GAP_MINUTES
            for (slot, d), meal in bundle.meal_vars.items()
            if d == day
        )
        for cand in snapshot.candidates:
            profile = enriched.access_by_poi.get(cand.poi_id or cand.cid)
            active_ret = bundle.active_ret_vars.get((cand.cid, day))
            if profile is not None and active_ret is not None:
                ends.append(
                    active_ret
                    + profile.ride_minutes
                    + profile.last_mile_minutes
                    + HOTEL_NIGHT_GAP_MINUTES
                )
        model.AddMaxEquality(night_start, ends)
        night_cap = model.NewIntVar(0, MINUTES_PER_DAY + 360, "hnc_%d" % day)
        night_end = model.NewIntVar(0, MINUTES_PER_DAY - 1, "hne_%d" % day)
        model.Add(night_cap == night_start + HOTEL_NIGHT_MINUTES)
        model.AddMinEquality(night_end, [night_cap, MINUTES_PER_DAY - 1])
        bundle.hotel_vars[("night", day)] = {
            "p": active,
            "start": night_start,
            "end": night_end,
        }


def _seatable_on_day(
    bundle: VarBundle, enriched: "EnrichedSnapshot", cand, day: int
) -> bool:
    if (cand.best_visit_time or "").lower() == "show" and is_sessionless_show(
        cand.best_visit_time, cand.opening_hours
    ):
        return False
    day_dt = day_date(enriched.snapshot.request.start_date, day)
    if day_dt is not None:
        if day_dt.weekday() in closed_weekdays(cand.opening_hours):
            return False
        weather = enriched.weather.get((cand.cid, day_dt.isoformat()))
        if weather and weather.get("forbid"):
            return False
    lo = DAY_START_MINUTES
    hi = 23 * 60 if cand.best_visit_time == "show" else DAY_END_MINUTES
    window = enriched.windows.get(cand.cid)
    if window is not None:
        lo = max(lo, window[0])
        hi = min(hi, window[1])
    minimum = enriched.tiers[cand.cid][0]
    cap = enriched.caps.get(cand.cid, (None, "unknown"))[0]
    return lo + minimum <= hi and (cap is None or lo <= cap)


def add_c14_coverage_before_fill(
    bundle: VarBundle, enriched: "EnrichedSnapshot"
) -> None:
    """A statically seatable must cannot remain unplaced beside a fill.

    Static seatability checks the candidate's own window/cap/weather. Global
    requested-vs-requested competition is settled by F-23 tier ①, which is
    strictly optimized before the fill reward in tier ②.
    """
    snapshot = enriched.snapshot
    fills = [c for c in snapshot.candidates if not c.rid]
    if not fills:
        return
    requested_rids = {r.rid for r in snapshot.request.musts}
    requested_rids.update({r.rid for r in snapshot.request.wishes})
    for cand in snapshot.candidates:
        if cand.rid not in requested_rids:
            continue
        for day in bundle.days:
            if not _seatable_on_day(bundle, enriched, cand, day):
                continue
            for fill in fills:
                bundle.model.Add(bundle.presence[(fill.cid, day)] == 0).OnlyEnforceIf(
                    bundle.unplaced[cand.rid]
                )


def add_c15_remote_departure(bundle: VarBundle, enriched: "EnrichedSnapshot") -> None:
    snapshot = enriched.snapshot
    fills = [c for c in snapshot.candidates if not c.rid]
    for remote in snapshot.candidates:
        if (remote.poi_id or remote.cid) not in enriched.access_by_poi:
            continue
        for day in bundle.days:
            pr = bundle.presence[(remote.cid, day)]
            for fill in fills:
                pf = bundle.presence[(fill.cid, day)]
                bundle.model.Add(
                    bundle.start[(fill.cid, day)]
                    >= bundle.start[(remote.cid, day)] + bundle.dur[remote.cid]
                ).OnlyEnforceIf([pr, pf])


def add_c16_diversity_caps(
    bundle: VarBundle, enriched: "EnrichedSnapshot", relax: bool = False
) -> None:
    """C-16; ``relax=True`` is F-25 rung 2 (diversity caps, disclosed)."""
    if relax:
        return
    snapshot = enriched.snapshot
    sight_cap = int(getattr(snapshot.request, "sight_cap_per_day", SIGHT_CAP_PER_DAY))
    fill_cap = int(getattr(snapshot.request, "fill_cap_per_day", FILL_CAP_PER_DAY))
    fills = [c for c in snapshot.candidates if not c.rid]
    sights = [c for c in snapshot.candidates if c.category not in NON_SIGHT_CATEGORIES]
    groups: dict[tuple[str, int], list] = {}
    for day in bundle.days:
        if sights:
            bundle.model.Add(
                sum(bundle.presence[(c.cid, day)] for c in sights) <= sight_cap
            )
        if fills:
            bundle.model.Add(
                sum(bundle.presence[(c.cid, day)] for c in fills) <= fill_cap
            )
        requested_load = sum(
            bundle.active_dur[(c.cid, day)]
            for c in snapshot.candidates
            if c.rid and c.category in SIGHT_CATEGORIES
        )
        for fill in fills:
            group = getattr(fill, "diversity_group", None)
            if group:
                groups.setdefault((group, day), []).append(
                    bundle.presence[(fill.cid, day)]
                )
            if fill.category in SIGHT_CATEGORIES:
                # Legacy heavy-day rule: once requested sights occupy ≥300
                # minutes, optional same-family sightseeing yields.
                bundle.model.Add(
                    requested_load
                    <= 299
                    + (DAY_LOAD_BUDGET_MINUTES + 1)
                    * (1 - bundle.presence[(fill.cid, day)])
                )
    for literals in groups.values():
        bundle.model.Add(sum(literals) <= 1)


def extract_meal_anchors(
    bundle: VarBundle, enriched: "EnrichedSnapshot", solver
) -> list[dict]:
    out: list[dict] = []
    for (slot, day), meal in sorted(
        bundle.meal_vars.items(), key=lambda pair: (pair[0][1], pair[0][0])
    ):
        if not solver.Value(meal["p"]):
            continue
        host_cid = next(
            (cid for cid, lit in meal["hosts"].items() if solver.Value(lit)), None
        )
        anchor = next(
            (
                cid
                for cid, gate in meal.get("anchor_candidates", ())
                if solver.Value(gate)
            ),
            None,
        )
        if anchor is not None:
            host_cid = anchor
        bound_cid = next(
            (cid for cid, lit in meal.get("bound", {}).items() if solver.Value(lit)),
            None,
        )
        out.append(
            {
                "slot": slot,
                "day": day,
                "start_min": solver.Value(meal["start"]),
                "end_min": solver.Value(meal["end"]),
                "host_cid": host_cid,
                "bound_cid": bound_cid,
            }
        )
    return out


def extract_hotel_anchors(
    bundle: VarBundle, enriched: "EnrichedSnapshot", solver
) -> list[dict]:
    out: list[dict] = []
    for (slot, day), hotel in sorted(
        bundle.hotel_vars.items(), key=lambda pair: (pair[0][1], pair[0][0])
    ):
        if not solver.Value(hotel["p"]):
            continue
        out.append(
            {
                "slot": slot,
                "day": day,
                "start_min": solver.Value(hotel["start"]),
                "end_min": solver.Value(hotel["end"]),
            }
        )
    return out
