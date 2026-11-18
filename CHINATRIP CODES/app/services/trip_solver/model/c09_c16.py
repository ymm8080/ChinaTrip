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

from app.services.itinerary.solver import (
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
            model.Add(lit == active)
            st = model.NewIntVar(0, MINUTES_PER_DAY, "ms_%s_%d" % (slot, day))
            du = model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(MEAL_DURATIONS[slot]),
                "md_%s_%d" % (slot, day),
            )
            en = model.NewIntVar(0, MINUTES_PER_DAY + 90, "me_%s_%d" % (slot, day))
            model.NewOptionalIntervalVar(st, du, en, lit, "mi_%s_%d" % (slot, day))
            lo, hi = MEAL_WINDOWS[slot]
            if slot == "lunch":
                # Ordinary cards keep the legacy 11:30–12:30 start band. A
                # remote day needs 11:00 arrival nesting and post-visit lunch.
                model.Add(st >= REMOTE_LUNCH_EARLIEST).OnlyEnforceIf(remote_day)
                model.Add(st >= lo).OnlyEnforceIf(remote_day.Not())
                model.Add(st <= hi).OnlyEnforceIf(remote_day.Not())
            else:
                model.Add(st >= lo).OnlyEnforceIf(lit)
                model.Add(st <= hi).OnlyEnforceIf(lit)

            meal = {
                "p": lit,
                "start": st,
                "dur": du,
                "end": en,
                "active_end": _active_end(model, "mae_%s_%d" % (slot, day), lit, en),
                "hosts": {},
                "anchor_candidates": [],
            }
            bundle.meal_vars[(slot, day)] = meal

            for cand in snapshot.candidates:
                p_cand = bundle.presence[(cand.cid, day)]
                c_start = bundle.start[(cand.cid, day)]
                c_end = c_start + bundle.dur[cand.cid]
                profiled = (cand.poi_id or cand.cid) in enriched.access_by_poi
                bound_food = (
                    cand.category == "food" and getattr(cand, "meal_slot", None) == slot
                )

                if bound_food:
                    # The system card is the slot; the real restaurant fills
                    # its data. Once selected, the binding cannot drift.
                    model.Add(st == c_start).OnlyEnforceIf(p_cand)
                    model.Add(du == bundle.dur[cand.cid]).OnlyEnforceIf(p_cand)
                    remote_bound = any(
                        getattr(cand, "same_venue", None) in (other.cid, other.poi_id)
                        for other in snapshot.candidates
                        if (other.poi_id or other.cid) in enriched.access_by_poi
                    )
                    if slot != "lunch" or not remote_bound:
                        model.Add(c_start >= lo).OnlyEnforceIf(p_cand)
                        model.Add(c_start <= hi).OnlyEnforceIf(p_cand)
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

            model.Add(lunch["p"] == 1).OnlyEnforceIf(lit)
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
            if sessionless or off_season:
                bundle.model.Add(lit == 0)
            elif sessions:
                bundle.model.AddAllowedAssignments(
                    [bundle.start[(cand.cid, day)]], [(s,) for s in sessions]
                ).OnlyEnforceIf(lit)
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
        if len(terms) > 1:
            bundle.model.Add(sum(terms) <= 1)


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
                taxi = int(profile.taxi_minutes or DEFAULT_GATEWAY_TAXI_MINUTES)
                ready = model.NewIntVar(
                    0, MINUTES_PER_DAY, "hr_%s_%d" % (cand.cid, day)
                )
                model.Add(ready == dep - taxi).OnlyEnforceIf(lit)
                model.Add(ready == 0).OnlyEnforceIf(lit.Not())
            else:
                ready = bundle.start[(cand.cid, day)]
                if not _is_pinned(snapshot, cand, day) and not (
                    day == 1 and snapshot.request.day1_start
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
        out.append(
            {
                "slot": slot,
                "day": day,
                "start_min": solver.Value(meal["start"]),
                "end_min": solver.Value(meal["end"]),
                "host_cid": host_cid,
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
