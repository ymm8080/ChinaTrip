"""F-23 lexicographic objectives (P1-D).

The four expressions are deliberately kept separate. ``solve`` optimizes them
in order and fixes each proven optimum before moving to the next tier; a large
fill/quality reward can therefore never purchase requested-coverage loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..inputs.weather import RAIN_INDOOR_PENALTY, is_rainy
from .c01_c04 import day_date
from .slack import SlackFlags

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot
    from .vars import VarBundle

FILL_REWARD = 100
# R1 设计镜像（打分器软罚一一对应、仅影响放置不涉时刻）：
# venue_strand 拆簇 −60（近簇跨日无伴）→ 同日共处 +60；
# no_entertainment −40/程（2026-11-03 拍板）→ 娱乐在场 +40
NEAR_PAIR_COLOCATE_REWARD = 60
ENTERTAINMENT_PRESENT_REWARD = 40
CATEGORY_DIVERSITY_REWARD = 20
QUALITY_SCALE = 100
# P2-B3 evidence: at 4/min a dense day's typ-shrinkage outbids
# FILL_REWARD (g01 both-fills net -10 at tier ①) and days starve; 1/min
# fixes density but trips the P0 audit (8-min transfer gaps, 17km walk
# days) until the taxi-call buffer / meal-gap / afternoon-big caps land.
# Kept 4/min through iter2 (constraints landed); iter3 blockers: walk-cap
# 15km/day + audit counts the materialised return card as a big visit.
DURATION_DEVIATION_PENALTY = 4
MEAL_DURATION_DEVIATION_PENALTY = 1
INDOOR_DINNER_REWARD = 80  # 2026-11-18 用户拍板：晚饭通常优先室内
WEEKEND_PENALTY = 90  # legacy _MUST_WEEKEND_PENALTY
RAIN_WEEKEND_EXTRA = 120  # legacy _MUST_RAIN_WEEKEND_EXTRA
REMOTE_RAIN_EXTRA = 60  # legacy _MUST_REMOTE_RAIN_EXTRA
SHOW_EARLY_PENALTY = 10_000  # legacy SHOW_EARLY_SESSION_PENALTY
SHOW_LATE_SESSION_MINUTES = 15 * 60


@dataclass
class ObjectiveTier:
    name: str
    expression: object
    sense: str  # min | max


def _coverage(bundle: "VarBundle", enriched: "EnrichedSnapshot") -> ObjectiveTier:
    request = enriched.snapshot.request
    weights = {r.rid: max(1, r.importance) for r in request.musts}
    weights.update({r.rid: 1 for r in request.wishes})
    expression = sum(
        bundle.unplaced[rid] * weights.get(rid, 1) for rid in bundle.unplaced
    )
    return ObjectiveTier("coverage", expression, "min")


def _preference(
    bundle: "VarBundle",
    enriched: "EnrichedSnapshot",
    slack: SlackFlags | None = None,
) -> ObjectiveTier:
    snapshot = enriched.snapshot
    model = bundle.model
    relax_tod = bool(slack and slack.relax_time_of_day)
    relax_wx = bool(slack and slack.relax_weather)
    positive: list = []
    negative: list = []
    weather_by_key = {(poi, day): cond for poi, day, cond in snapshot.weather}

    for cand in snapshot.candidates:
        tier = enriched.tiers[cand.cid]
        deviation = model.NewIntVar(0, tier[2], "obj_dd_%s" % cand.cid)
        model.AddAbsEquality(deviation, bundle.dur[cand.cid] - tier[1])
        negative.append(DURATION_DEVIATION_PENALTY * deviation)

        quality = int(round(float(cand.quality or 0) * QUALITY_SCALE))
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            if quality:
                positive.append(quality * lit)
            if not cand.rid:
                positive.append(FILL_REWARD * lit)
            if (
                cand.category == "food"
                and getattr(cand, "meal_slot", None) == "dinner"
                and str(cand.indoor or "").lower() in {"yes", "true", "1", "indoor"}
            ):
                positive.append(INDOOR_DINNER_REWARD * lit)

            day_dt = day_date(snapshot.request.start_date, day)
            iso = day_dt.isoformat() if day_dt is not None else None
            condition = weather_by_key.get((cand.poi_id, iso))
            rainy = is_rainy(condition)
            if (
                cand.rid
                and day_dt is not None
                and day_dt.weekday() >= 5
                and not (relax_tod or relax_wx)
            ):
                negative.append(WEEKEND_PENALTY * lit)
                if rainy:
                    negative.append(RAIN_WEEKEND_EXTRA * lit)
            if rainy and not relax_wx:
                weather = enriched.weather.get((cand.cid, iso))
                if weather:
                    negative.append(int(weather["penalty"]) * lit)
                else:
                    # Indoor requested/fill items retain the legacy lighter
                    # rainy-day cost instead of the outdoor 240-minute cost.
                    negative.append(RAIN_INDOOR_PENALTY * lit)
                if cand.rid and cand.remote:
                    negative.append(REMOTE_RAIN_EXTRA * lit)

            if (cand.best_visit_time or "").lower() == "show" and not relax_tod:
                early = model.NewBoolVar("obj_se_%s_%d" % (cand.cid, day))
                model.Add(early <= lit)
                start = bundle.start[(cand.cid, day)]
                model.Add(start < SHOW_LATE_SESSION_MINUTES).OnlyEnforceIf([lit, early])
                model.Add(start >= SHOW_LATE_SESSION_MINUTES).OnlyEnforceIf(
                    [lit, early.Not()]
                )
                negative.append(SHOW_EARLY_PENALTY * early)

    # R1 拆簇镜像：近距对（打分器 _near_mate_km 同源口径，取
    # solver.NEAR_SAMEDAY_KM）同日共处奖励——O(对数) 公式：dayVar
    # 相等 ⇔ 同日（双方都已排），不按 天×对 展开防爆项
    from app.services.itinerary.solver import NEAR_SAMEDAY_KM as _near_km

    from ..inputs.travel import haversine_km as _hk

    cands = list(snapshot.candidates)
    for i, a in enumerate(cands):
        for b in cands[i + 1 :]:
            # requested-involved pruning (R3a): fill×fill colocate is
            # secondary — keeps the pair count provable at trip scale
            # (g11 tier② timed out at 0.4 dtime with all-pairs)
            if not (a.rid or b.rid):
                continue
            if a.lon is None or a.lat is None or b.lon is None or b.lat is None:
                continue
            if a.city and b.city and a.city != b.city:
                continue  # C-07 已禁跨城同日，不必奖励
            if _hk(a.lon, a.lat, b.lon, b.lat) > _near_km:
                continue
            day_a = sum(day * bundle.presence[(a.cid, day)] for day in bundle.days)
            day_b = sum(day * bundle.presence[(b.cid, day)] for day in bundle.days)
            bp = model.NewBoolVar("obj_bp_%s_%s" % (a.cid, b.cid))
            pa = model.NewBoolVar("obj_pa_%s" % a.cid)
            pb = model.NewBoolVar("obj_pb_%s" % b.cid)
            model.AddMaxEquality(pa, [bundle.presence[(a.cid, d)] for d in bundle.days])
            model.AddMaxEquality(pb, [bundle.presence[(b.cid, d)] for d in bundle.days])
            model.AddBoolAnd([pa, pb]).OnlyEnforceIf(bp)
            model.AddBoolOr([pa.Not(), pb.Not()]).OnlyEnforceIf(bp.Not())
            rb = model.NewBoolVar("obj_near_%s_%s" % (a.cid, b.cid))
            # 只锁等向+双排守卫：最大化驱动 rb=1（等日且双排）；
            # 双未排（0==0）拿不到——bp=0 挡住。无 ≠ 分支（会双未排矛盾）
            model.Add(day_a == day_b).OnlyEnforceIf(rb)
            model.AddImplication(rb, bp)
            positive.append(NEAR_PAIR_COLOCATE_REWARD * rb)

    # R1 娱乐镜像：全程 ≥1 娱乐/演出类在场
    ent_lits = [
        bundle.presence[(cand.cid, day)]
        for cand in snapshot.candidates
        if (cand.category or "") == "entertainment"
        or (cand.best_visit_time or "").lower() == "show"
        for day in bundle.days
    ]
    if ent_lits:
        ent_any = model.NewBoolVar("obj_ent_any")
        model.AddMaxEquality(ent_any, ent_lits)
        positive.append(ENTERTAINMENT_PRESENT_REWARD * ent_any)

    categories = sorted({c.category or "other" for c in snapshot.candidates})
    for category in categories:
        members = [
            c for c in snapshot.candidates if (c.category or "other") == category
        ]
        for day in bundle.days:
            active = model.NewBoolVar("obj_cat_%s_%d" % (category, day))
            model.AddMaxEquality(
                active, [bundle.presence[(c.cid, day)] for c in members]
            )
            positive.append(CATEGORY_DIVERSITY_REWARD * active)

    for (slot, _day), meal in bundle.meal_vars.items():
        default = 60 if slot == "lunch" else 90
        deviation = model.NewIntVar(0, 90, "obj_md_%s_%d" % (slot, _day))
        model.AddAbsEquality(deviation, meal["dur"] - default)
        negative.append(MEAL_DURATION_DEVIATION_PENALTY * deviation)

    expression = sum(positive) - sum(negative)
    return ObjectiveTier("preference", expression, "max")


def _travel(bundle: "VarBundle", enriched: "EnrichedSnapshot") -> ObjectiveTier:
    return ObjectiveTier("travel", sum(bundle.travel_terms), "min")


def _makespan(bundle: "VarBundle", enriched: "EnrichedSnapshot") -> ObjectiveTier:
    model = bundle.model
    terms: list = []
    for day in bundle.days:
        end = model.NewIntVar(0, 24 * 60 + 300, "obj_day_end_%d" % day)
        ends = [bundle.active_end[(c.cid, day)] for c in enriched.snapshot.candidates]
        ends.extend(
            meal["active_end"]
            for (slot, d), meal in bundle.meal_vars.items()
            if d == day
        )
        model.AddMaxEquality(end, ends or [0])
        bundle.day_end_vars[day] = end
        terms.append(end)

    # C-08's chosen outbound/return departures are zero when absent. Including
    # them here implements the early-bus preference without disturbing any
    # higher tier or allowing lunch to choose the outbound departure.
    terms.extend(bundle.active_dep_vars.values())
    terms.extend(bundle.active_ret_vars.values())
    return ObjectiveTier("makespan_early_access", sum(terms), "min")


def build_objectives(
    bundle: "VarBundle",
    enriched: "EnrichedSnapshot",
    slack: SlackFlags | None = None,
) -> list[ObjectiveTier]:
    return [
        _coverage(bundle, enriched),
        _preference(bundle, enriched, slack),
        _travel(bundle, enriched),
        _makespan(bundle, enriched),
    ]
