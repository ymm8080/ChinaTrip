"""P1-D model-core tests: C-09..C-16, F-22 and F-23.

Synthetic fixtures keep each rule isolated; G-01 anchors the incident shape.
Every assertion describes a user-visible invariant, not an implementation detail.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.snapshot import (
    default_golden_path,
    load_golden,
    snapshot_from_dict,
    snapshot_hash,
)
from app.services.trip_solver.types import FixedPin

G01 = default_golden_path()


def _cand(
    cid: str,
    *,
    name: str | None = None,
    rid: str | None = None,
    category: str = "attraction",
    hours: str = "08:00-20:00",
    duration: int = 60,
    best_visit_time: str = "any",
    **extra,
):
    return {
        "cid": cid,
        "name": name or cid,
        "poi_id": f"p-{cid}",
        "kind": "requested" if rid else "fill",
        "rid": rid,
        "category": category,
        "opening_hours": hours,
        "best_visit_time": best_visit_time,
        "suggested_duration_min": duration,
        **extra,
    }


def _snap(
    candidates,
    *,
    days: int = 1,
    musts=(),
    wishes=(),
    start_date: str | None = None,
    pins=(),
    access_profiles=(),
    travel=(),
    weather=(),
    request_extra=None,
):
    req = [
        {
            "rid": r if isinstance(r, str) else r["rid"],
            "name": r if isinstance(r, str) else r.get("name", r["rid"]),
            "poi_id": f"p-{r}" if isinstance(r, str) else r.get("poi_id"),
            "kind": "must",
            "importance": 3,
            **({} if isinstance(r, str) else r),
        }
        for r in musts
    ]
    raw = {
        "schema_version": 2,
        "request": {
            "days": days,
            "cities": ("北京",),
            "start_date": start_date,
            "musts": req,
            "wishes": wishes,
            "pins": pins,
            **(request_extra or {}),
        },
        "candidates": candidates,
        "access_profiles": access_profiles,
        "travel": travel,
        "weather": weather,
        "source": "synthetic-p1d",
    }
    return snapshot_from_dict(raw)


def _solve(snapshot):
    return solve_snapshot(enrich(snapshot))


def _ok(sol):
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status


def _meal(sol, slot: str, day: int = 1):
    return next(
        m
        for m in getattr(sol, "meal_anchors", [])
        if m["slot"] == slot and m["day"] == day
    )


def _hotel(sol, slot: str, day: int = 1):
    return next(
        h
        for h in getattr(sol, "hotel_anchors", [])
        if h["slot"] == slot and h["day"] == day
    )


# ---------- C-09 meal anchors / real restaurant binding ----------


def test_c09_meal_anchors_use_windows_and_nest_or_avoid_overlap():
    snap = _snap([_cand("site", rid="r-site", duration=480)], musts=("r-site",))
    sol = _solve(snap)
    _ok(sol)
    lunch = _meal(sol, "lunch")
    dinner = _meal(sol, "dinner")
    assert 11 * 60 + 30 <= lunch["start_min"] <= 12 * 60 + 30
    assert lunch["end_min"] - lunch["start_min"] in {30, 45, 60}
    assert 17 * 60 <= dinner["start_min"] <= 19 * 60 + 30
    assert dinner["end_min"] - dinner["start_min"] in {45, 60, 90}
    site = next(i for i in sol.items if i.cid == "site")
    for meal in (lunch, dinner):
        if meal["host_cid"] == "site":
            assert meal["start_min"] >= site.start_min
            assert meal["end_min"] <= site.end_min
        else:
            assert (
                meal["end_min"] <= site.start_min or meal["start_min"] >= site.end_min
            )


def test_c09_real_restaurant_binds_lunch_and_nests_at_same_venue():
    site = _cand("site", rid="r-site", duration=240)
    food = _cand(
        "food",
        rid="r-food",
        category="food",
        hours="11:30-13:30",
        duration=60,
        meal_slot="lunch",
        same_venue="site",
    )
    snap = _snap(
        [site, food],
        musts=("r-site", "r-food"),
        pins=({"rid": "r-food", "day": 1, "start_min": 720},),
    )
    sol = _solve(snap)
    _ok(sol)
    placed = {i.cid: i for i in sol.items}
    assert placed["food"].start_min == 720  # user pin + real binding immovable
    lunch = _meal(sol, "lunch")
    assert lunch["start_min"] == placed["food"].start_min
    assert lunch["end_min"] == placed["food"].end_min
    assert lunch["host_cid"] == "site"
    assert placed["site"].start_min <= 720
    assert placed["site"].end_min >= placed["food"].end_min


# ---------- C-10 + F-22 remote lunch ----------


def test_remote_lunch_first_at_1108_and_earliest_feasible_bus():
    snapshot, _, _ = load_golden(G01)
    request = replace(
        snapshot.request,
        pins=(replace(snapshot.request.pins[0], day=1, start_min=430),)
        if snapshot.request.pins
        else (),
    )
    if not request.pins:
        from app.services.trip_solver.types import FixedPin

        request = replace(request, pins=(FixedPin(rid="r1", day=1, start_min=430),))
    sol = _solve(replace(snapshot, request=request))
    _ok(sol)
    mty = next(i for i in sol.items if i.cid == "c3")
    leg = next(leg for leg in sol.access_legs if leg["cid"] == "c3")
    lunch = _meal(sol, "lunch", mty.day)
    # iter2 审计对齐后同为最优的合法形状有两种：升旗锚当日（09:30 班）
    # 或故宫晨锚换日（10:30 班）——班次始终跟随实际晨锚的最早可行班
    _names = {c.cid: c.name for c in snapshot.candidates}
    _tian = next((i for i in sol.items if _names[i.cid] == "天安门广场"), None)
    if _tian is not None and _tian.day == mty.day:
        assert leg["depart_min"] == 570  # 09:30: 正典（07:10–08:40 + taxi）
    else:
        assert leg["depart_min"] in (510, 570, 630)  # 跟随其晨锚的最早班
    assert leg["arrive_poi_min"] == leg["depart_min"] + 98  # 90 ride + 8 last-mile
    assert lunch["start_min"] == leg["arrive_poi_min"]  # F-22: lunch at arrival
    assert mty.start_min == lunch["end_min"]  # visit after lunch (Q4)
    assert lunch["host_cid"] == "c3"
    assert leg["visit_start_min"] == mty.start_min


def test_remote_arrival_before_11_visits_first_then_lunches():
    remote = _cand("remote", rid="r-remote", category="historic", duration=120)
    snap = _snap(
        [remote],
        musts=("r-remote",),
        access_profiles=(
            {
                "gateway": "城心",
                "to_poi": "p-remote",
                "ride_minutes": 90,
                "last_mile_minutes": 0,
                "departures": ("07:30",),
                "returns": ("15:00",),
            },
        ),
    )
    sol = _solve(snap)
    _ok(sol)
    visit = next(i for i in sol.items if i.cid == "remote")
    leg = sol.access_legs[0]
    lunch = _meal(sol, "lunch")
    assert leg["arrive_poi_min"] == 9 * 60  # Q4: before 11:00 → visit first
    assert visit.start_min == 9 * 60
    assert lunch["start_min"] >= visit.end_min
    assert lunch["start_min"] >= leg["depart_min"]  # never a city pre-departure lunch


# ---------- C-09 entertainment exclusion ----------


def test_c09_meals_do_not_nest_in_entertainment():
    show = _cand(
        "show",
        rid="r-show",
        category="entertainment",
        hours="08:00-20:00",
        duration=480,
    )
    sol = _solve(_snap([show], musts=("r-show",)))
    _ok(sol)
    visit = sol.items[0]
    for slot in ("lunch", "dinner"):
        meal = _meal(sol, slot)
        assert meal["host_cid"] != "show"
        assert meal["end_min"] <= visit.start_min or meal["start_min"] >= visit.end_min


def test_f23_access_travel_counts_outbound_without_return_timetable():
    remote = _cand("remote", rid="r-remote", category="historic", duration=120)
    snap = _snap(
        [remote],
        musts=("r-remote",),
        days=2,
        pins=({"rid": "r-remote", "day": 1, "start_min": 540},),
        access_profiles=(
            {
                "gateway": "城心",
                "to_poi": "p-remote",
                "ride_minutes": 90,
                "last_mile_minutes": 0,
                "departures": ("07:30",),
                "returns": (),
            },
        ),
    )
    sol = _solve(snap)
    _ok(sol)
    assert sol.objective_values["travel"] == 2 * 90 + 15


def test_wish_coverage_dominates_high_quality_fill():
    wish = _cand(
        "wish",
        rid="r-wish",
        hours="11:30-12:00",
        duration=60,
    )
    fill = _cand(
        "fill",
        hours="11:30-13:00",
        duration=60,
        quality=10,
    )
    snap = _snap(
        [wish, fill],
        wishes=(
            {
                "rid": "r-wish",
                "name": "wish",
                "poi_id": "p-wish",
                "kind": "wish",
                "importance": 2,
            },
        ),
    )
    sol = _solve(snap)
    _ok(sol)
    assert [i.cid for i in sol.items] == ["wish"]
    assert [u["rid"] for u in sol.unplaced] == []


def test_c09_unbound_real_food_never_overlaps_system_meal():
    food = _cand(
        "food",
        category="food",
        hours="11:30-14:00",
        duration=60,
    )
    sol = _solve(_snap([food]))
    _ok(sol)
    lunch = _meal(sol, "lunch")
    food_item = sol.items[0]
    assert (
        lunch["end_min"] <= food_item.start_min
        or lunch["start_min"] >= food_item.end_min
    )


def test_remote_dinner_never_overlaps_visit_without_return_timetable():
    remote = _cand(
        "remote",
        rid="r-remote",
        category="historic",
        duration=600,
    )
    snap = _snap(
        [remote],
        musts=("r-remote",),
        access_profiles=(
            {
                "gateway": "城心",
                "to_poi": "p-remote",
                "ride_minutes": 90,
                "last_mile_minutes": 0,
                "departures": ("07:30",),
                "returns": (),
            },
        ),
    )
    sol = _solve(snap)
    _ok(sol)
    visit = sol.items[0]
    dinner = _meal(sol, "dinner")
    assert dinner["end_min"] <= visit.start_min or dinner["start_min"] >= visit.end_min


def test_budget_exhaustion_is_unknown_not_infeasible():
    snapshot, _, _ = load_golden(G01)
    sol = solve_snapshot(enrich(snapshot), budget_s=0.0)
    assert sol.status == "UNKNOWN"
    assert sol.items == []
    assert sol.certificate == []


def test_snapshot_hash_distinguishes_every_solver_input_family():
    from dataclasses import replace

    snapshot, _, _ = load_golden(G01)
    assert snapshot.schema_version == 2
    base = snapshot_hash(snapshot)

    def with_first_candidate(**changes):
        return (replace(snapshot.candidates[0], **changes),) + snapshot.candidates[1:]

    variants = [
        replace(
            snapshot,
            request=replace(
                snapshot.request,
                pins=(FixedPin(rid="r1", day=1, start_min=430),),
            ),
        ),
        replace(snapshot, candidates=with_first_candidate(quality=0.9)),
        replace(snapshot, candidates=with_first_candidate(best_visit_time="morning")),
        replace(snapshot, candidates=with_first_candidate(indoor="yes")),
        replace(
            snapshot,
            request=replace(snapshot.request, preferences="喜欢博物馆人文"),
        ),
    ]
    assert len({base, *(snapshot_hash(v) for v in variants)}) == len(variants) + 1


# ---------- C-11 shows ----------


def test_c11_show_uses_declared_session_and_allows_only_one_per_day():
    a = _cand(
        "show-a",
        rid="r-a",
        category="entertainment",
        best_visit_time="show",
        hours="约19:30一场",
        duration=60,
    )
    b = _cand(
        "show-b",
        rid="r-b",
        category="entertainment",
        best_visit_time="show",
        hours="约20:30一场",
        duration=60,
    )
    sol = _solve(_snap([a, b], musts=("r-a", "r-b")))
    _ok(sol)
    assert len(sol.items) == 1
    assert len(sol.unplaced) == 1
    assert sol.items[0].start_min in {19 * 60 + 30, 20 * 60 + 30}


def test_c11_sessionless_show_is_excluded_not_silently_timetabled():
    show = _cand(
        "show",
        rid="r-show",
        category="entertainment",
        best_visit_time="show",
        hours=None,
        duration=60,
    )
    sol = _solve(_snap([show], musts=("r-show",)))
    _ok(sol)
    assert sol.items == []
    assert [u["rid"] for u in sol.unplaced] == ["r-show"]


def test_c11_off_season_show_is_excluded_but_in_season_uses_session():
    show = _cand(
        "show",
        rid="r-show",
        category="entertainment",
        best_visit_time="show",
        hours="仅夜场（约20:10场；演出季4-10月，冬季停演）",
        duration=60,
    )
    winter = _solve(_snap([show], musts=("r-show",), start_date="2026-11-25"))
    _ok(winter)
    assert winter.items == []
    assert [u["rid"] for u in winter.unplaced] == ["r-show"]

    in_season = _solve(_snap([show], musts=("r-show",), start_date="2026-10-01"))
    _ok(in_season)
    assert in_season.items[0].start_min == 20 * 60 + 10


# ---------- C-12 family / load / weather-day preference ----------


def test_c12_explicit_must_family_never_splits_across_days():
    a = _cand("a", rid="r-a", hours="周二至周日08:00-20:00", family_id="fam")
    b = _cand("b", rid="r-b", hours="周一关闭,08:00-20:00", family_id="fam")
    # 2026-11-23 is Monday: A is closed Tuesday by its weekday list parser only
    # when an explicit closed marker exists, so use complementary closed markers.
    a["opening_hours"] = "周二关闭,08:00-20:00"
    snap = _snap([a, b], musts=("r-a", "r-b"), days=2, start_date="2026-11-23")
    sol = _solve(snap)
    _ok(sol)
    assert sol.items == []  # no single day can hold the family; never split it
    assert {u["rid"] for u in sol.unplaced} == {"r-a", "r-b"}


def test_c12_day_load_budget_forces_honest_unplaced():
    candidates = [_cand(f"s{i}", rid=f"r{i}", duration=300) for i in range(4)]
    sol = _solve(_snap(candidates, musts=tuple(f"r{i}" for i in range(4))))
    _ok(sol)
    assert len(sol.items) == 3  # 4 × 150 minimum > 570-minute usable day
    assert len(sol.unplaced) == 1


def test_c12_clear_weekend_beats_rainy_weekday_for_outdoor_must():
    outdoor = _cand("outdoor", rid="r-out", category="park", duration=120, rain_ok="no")
    snap = _snap(
        [outdoor],
        musts=("r-out",),
        days=2,
        start_date="2026-11-20",  # Friday → Saturday
        weather=(("p-outdoor", "2026-11-20", "moderate rain"),),
    )
    sol = _solve(snap)
    _ok(sol)
    assert sol.items[0].day == 2  # rain 240 > clear-weekend 90


# ---------- C-09/C-13 remote dinner + hotel anchors ----------


def test_remote_dinner_waits_until_after_return_arrival():
    from app.services.trip_solver.types import FixedPin

    snapshot, _, _ = load_golden(G01)
    snapshot = replace(
        snapshot,
        request=replace(
            snapshot.request,
            pins=(FixedPin(rid="r1", day=1, start_min=430),),
        ),
    )
    sol = _solve(snapshot)
    _ok(sol)
    leg = sol.access_legs[0]
    dinner = _meal(sol, "dinner", leg["day"])
    assert dinner["start_min"] >= leg["arrive_city_min"]


def test_remote_dinner_defaults_to_city_at_1930_boundary():
    remote = _cand("remote", rid="r-remote", category="historic", duration=120)
    snap = _snap(
        [remote],
        musts=("r-remote",),
        access_profiles=(
            {
                "gateway": "城心",
                "to_poi": "p-remote",
                "ride_minutes": 90,
                "last_mile_minutes": 0,
                "departures": ("07:30",),
                "returns": ("18:00",),
            },
        ),
    )
    sol = _solve(snap)
    _ok(sol)
    leg = sol.access_legs[0]
    dinner = _meal(sol, "dinner")
    assert leg["arrive_city_min"] == 19 * 60 + 30
    assert dinner["start_min"] >= leg["arrive_city_min"]
    assert dinner["host_cid"] != "remote"


def test_remote_dinner_allowed_when_return_would_miss_1930():
    remote = _cand("remote", rid="r-remote", category="historic", duration=120)
    snap = _snap(
        [remote],
        musts=("r-remote",),
        access_profiles=(
            {
                "gateway": "城心",
                "to_poi": "p-remote",
                "ride_minutes": 90,
                "last_mile_minutes": 0,
                "departures": ("07:30",),
                "returns": ("20:00",),
            },
        ),
    )
    sol = _solve(snap)
    _ok(sol)
    assert sol.unplaced == []  # do not sacrifice the remote must to avoid late dinner
    leg = sol.access_legs[0]
    dinner = _meal(sol, "dinner")
    night = _hotel(sol, "night")
    assert leg["arrive_city_min"] > 19 * 60 + 30
    assert dinner["host_cid"] == "remote"
    assert dinner["start_min"] >= sol.items[0].end_min
    assert dinner["end_min"] + 8 <= leg["return_depart_min"]
    assert night["start_min"] >= leg["arrive_city_min"] + 30


def test_dinner_real_restaurant_prefers_indoor():
    outdoor = _cand(
        "a-outdoor",
        category="food",
        hours="17:00-19:30",
        duration=60,
        meal_slot="dinner",
        indoor="no",
    )
    indoor = _cand(
        "z-indoor",
        category="food",
        hours="17:00-19:30",
        duration=60,
        meal_slot="dinner",
        indoor="yes",
    )
    sol = _solve(_snap([outdoor, indoor]))
    _ok(sol)
    assert [i.cid for i in sol.items] == ["z-indoor"]
    outdoor_score = _solve(_snap([outdoor])).objective_values["preference"]
    indoor_score = _solve(_snap([indoor])).objective_values["preference"]
    assert indoor_score > outdoor_score  # same restaurant; only indoor differs


def test_explicit_remote_lunch_restaurant_binds_arrival_then_visit():
    remote = _cand("remote", rid="r-remote", category="historic", duration=180)
    food = _cand(
        "food",
        rid="r-food",
        category="food",
        hours="11:00-13:00",
        duration=60,
        meal_slot="lunch",
        same_venue="remote",
        indoor="yes",
    )
    snap = _snap(
        [remote, food],
        musts=("r-remote", "r-food"),
        access_profiles=(
            {
                "gateway": "城心",
                "to_poi": "p-remote",
                "ride_minutes": 90,
                "last_mile_minutes": 8,
                "departures": ("09:30",),
                "returns": ("15:30",),
            },
        ),
    )
    sol = _solve(snap)
    _ok(sol)
    placed = {i.cid: i for i in sol.items}
    lunch = _meal(sol, "lunch")
    assert placed["food"].start_min == 668
    assert placed["remote"].start_min == placed["food"].end_min
    assert lunch["start_min"] == placed["food"].start_min
    assert lunch["end_min"] == placed["food"].end_min
    assert lunch["host_cid"] == "remote"


def test_explicit_remote_dinner_overrides_default_city_preference():
    remote = _cand("remote", rid="r-remote", category="historic", duration=120)
    food = _cand(
        "food",
        rid="r-food",
        category="food",
        hours="17:00-19:30",
        duration=60,
        meal_slot="dinner",
        same_venue="remote",
        indoor="yes",
    )
    snap = _snap(
        [remote, food],
        musts=("r-remote", "r-food"),
        access_profiles=(
            {
                "gateway": "城心",
                "to_poi": "p-remote",
                "ride_minutes": 90,
                "last_mile_minutes": 0,
                "departures": ("07:30",),
                "returns": ("18:00",),
            },
        ),
    )
    sol = _solve(snap)
    _ok(sol)
    placed = {i.cid: i for i in sol.items}
    leg = sol.access_legs[0]
    dinner = _meal(sol, "dinner")
    assert dinner["host_cid"] == "remote"
    assert dinner["start_min"] == placed["food"].start_min
    assert dinner["end_min"] == placed["food"].end_min
    assert dinner["end_min"] + 8 <= leg["return_depart_min"]


# ---------- C-13 hotel anchors ----------


def test_c13_hotel_morning_precedes_early_pin_and_night_follows_last_item():
    site = _cand("site", rid="r-site", hours="03:30-20:00", duration=90)
    snap = _snap(
        [site],
        musts=("r-site",),
        pins=({"rid": "r-site", "day": 1, "start_min": 430},),
    )
    sol = _solve(snap)
    _ok(sol)
    morning = _hotel(sol, "morning")
    night = _hotel(sol, "night")
    dinner = _meal(sol, "dinner")
    assert morning["end_min"] <= 400  # 07:10 pin − 30-minute ride
    assert morning["end_min"] - morning["start_min"] == 30
    last_end = max(sol.items[0].end_min, dinner["end_min"])
    assert night["start_min"] >= last_end + 30
    assert 0 < night["end_min"] - night["start_min"] <= 60


# ---------- C-14 / C-15 coverage and remote departure ----------


def test_c14_fill_cannot_displace_seatable_must():
    must = _cand("must", rid="r-must", hours="09:00-13:00", duration=240)
    fill = _cand("fill", hours="09:00-13:00", duration=240, quality=1000)
    sol = _solve(_snap([must, fill], musts=("r-must",)))
    _ok(sol)
    assert [i.cid for i in sol.items] == ["must"]
    assert sol.unplaced == []


def test_c14_genuinely_unseatable_must_does_not_block_fill():
    must = _cand("must", rid="r-must", hours="09:00-09:30", duration=120)
    fill = _cand("fill", hours="09:00-17:00", duration=60)
    sol = _solve(_snap([must, fill], musts=("r-must",)))
    _ok(sol)
    assert [i.cid for i in sol.items] == ["fill"]
    assert [u["rid"] for u in sol.unplaced] == ["r-must"]


def test_c15_no_unrequested_item_precedes_remote_access():
    snapshot, _, _ = load_golden(G01)
    sol = _solve(snapshot)
    _ok(sol)
    by_cid = {c.cid: c for c in snapshot.candidates}
    leg = sol.access_legs[0]
    same_day_fills = [
        i for i in sol.items if i.day == leg["day"] and not by_cid[i.cid].rid
    ]
    assert same_day_fills == []  # C-06 is stricter; C-15 bans pre-departure too


# ---------- C-16 caps + F-23 travel / determinism ----------


def test_c16_daily_sight_cap_and_fill_pool_cap():
    sights = [_cand(f"s{i}", duration=30) for i in range(5)]
    sol = _solve(_snap(sights))
    _ok(sol)
    assert len(sol.items) == 4

    shows = [_cand(f"e{i}", category="entertainment", duration=30) for i in range(7)]
    sol2 = _solve(_snap(shows))
    _ok(sol2)
    assert len(sol2.items) == 6


def test_c16_diversity_group_limits_optional_duplicates():
    candidates = [
        _cand("a", category="entertainment", diversity_group="same", duration=30),
        _cand("b", category="entertainment", diversity_group="same", duration=30),
        _cand("c", category="entertainment", diversity_group="other", duration=30),
    ]
    sol = _solve(_snap(candidates))
    _ok(sol)
    assert {i.cid for i in sol.items} in ({"a", "c"}, {"b", "c"})


def test_f23_travel_tier_chooses_shorter_direction_after_coverage():
    a = _cand("a", rid="r-a", duration=60)
    b = _cand("b", rid="r-b", duration=60)
    travel = (
        {"from_key": "p-a", "to_key": "p-b", "minutes": 10},
        {"from_key": "p-b", "to_key": "p-a", "minutes": 60},
    )
    sol = _solve(_snap([a, b], musts=("r-a", "r-b"), travel=travel))
    _ok(sol)
    ordered = sorted(sol.items, key=lambda i: i.start_min)
    assert [i.cid for i in ordered] == ["a", "b"]
    assert ordered[1].start_min >= ordered[0].end_min + 10


def test_p1d_solution_is_deterministic_including_auxiliary_anchors():
    snapshot, _, _ = load_golden(G01)
    enriched = enrich(snapshot)
    a = solve_snapshot(enriched)
    b = solve_snapshot(enriched)

    def shape(s):
        return (
            [(i.cid, i.day, i.start_min, i.end_min) for i in s.items],
            s.access_legs,
            getattr(s, "meal_anchors", []),
            getattr(s, "hotel_anchors", []),
            s.unplaced,
        )

    assert shape(a) == shape(b)


def test_large_snapshot_timeout_prefix_is_deterministic():
    snapshot, _, _ = load_golden(G01)
    base = next(c for c in snapshot.candidates if c.cid == "c2")
    categories = ("attraction", "entertainment", "tea_experience", "citywalk", "museum")
    extra = []
    for index in range(10):
        extra.append(
            replace(
                base,
                cid=f"fx{index}",
                name=f"压力补点{index}",
                category=categories[index % len(categories)],
                suggested_duration_min=30 + 30 * (index % 2),
                quality=1 + index / 10,
                lon=116.35 + index * 0.005,
                lat=39.85 + index * 0.004,
            )
        )
    stress = replace(snapshot, candidates=snapshot.candidates + tuple(extra))
    first = solve_snapshot(enrich(stress))
    second = solve_snapshot(enrich(stress))

    def timeout_shape(solution):
        return (
            solution.status,
            [(i.cid, i.day, i.start_min, i.end_min) for i in solution.items],
            solution.access_legs,
            solution.meal_anchors,
            solution.hotel_anchors,
            solution.unplaced,
            solution.objective_values,
        )

    assert timeout_shape(first) == timeout_shape(second)


def test_preference_reward_boosts_preferred_category():
    """R8（拍板「偏好重排也要换 CP-SAT」）：偏好同类候选在场 +40/日——
    单坑对决里偏好压过 quality 差（legacy「偏好位在 tier 之前」同向）。"""

    from app.services.trip_solver.inputs.enrich import enrich
    from app.services.trip_solver.model.solve import solve_snapshot
    from app.services.trip_solver.types import CandidateItem, FactSnapshot, TripRequest

    def cand(cid, name, cat, tier, quality, lon, lat):
        return CandidateItem(
            cid=cid,
            name=name,
            category=cat,
            tier=tier,
            quality=quality,
            lon=lon,
            lat=lat,
            opening_hours="09:00-18:00",
            suggested_duration_min=90,
        )

    def snap(prefs):
        return FactSnapshot(
            schema_version=2,
            request=TripRequest(
                days=1,
                cities=("上海",),
                preferences=prefs,
                sight_cap_per_day=1,
            ),
            candidates=(
                cand("park", "中山公园", "park", 1, 0.9, 121.42, 31.22),
                cand("museum", "上海美术馆", "art", 4, 0.7, 121.47, 31.23),
            ),
        )

    def placed_names(snapshot):
        sol = solve_snapshot(enrich(snapshot), budget_s=3.0)
        return [i.cid for i in sol.items if i.kind == "visit"]

    control = placed_names(snap(""))
    assert "park" in control and "museum" not in control

    boosted = placed_names(snap("喜欢博物馆人文"))
    assert "museum" in boosted and "park" not in boosted


# ---------- R8-S2b: food must, any-slot real restaurant ----------


def test_food_must_any_slot_binds_exactly_one_meal():
    site = _cand("site", rid="r-site", category="historic", duration=90)
    food = _cand(
        "resto",
        rid="r-food",
        name="福和慧",
        category="food",
        hours="11:00-20:30",
        duration=60,
        meal_slot="any",
    )
    sol = _solve(_snap([site, food], musts=("r-site", "r-food")))
    _ok(sol)
    placed = {i.cid: i for i in sol.items}
    f = placed["resto"]
    from app.services.trip_solver.model.c09_c16 import MEAL_WINDOWS

    lo_l, hi_l = MEAL_WINDOWS["lunch"]
    lo_d, hi_d = MEAL_WINDOWS["dinner"]
    assert lo_l <= f.start_min <= hi_l or lo_d <= f.start_min <= hi_d
    bound = [m for m in sol.meal_anchors if m.get("bound_cid") == "resto"]
    assert len(bound) == 1
    assert bound[0]["start_min"] == f.start_min
    assert bound[0]["end_min"] == f.end_min
    # 未绑的另一槽照常出系统餐卡（host/bound 均非本餐厅）
    other = [m for m in sol.meal_anchors if m.get("bound_cid") != "resto"]
    assert all(m.get("bound_cid") is None for m in other)


def test_food_must_any_slot_assembles_single_named_card():
    from app.services.trip_solver.assembly import assemble

    site = _cand(
        "site",
        rid="r-site",
        category="historic",
        duration=90,
        lon=121.47,
        lat=31.23,
    )
    food = _cand(
        "resto",
        rid="r-food",
        name="福和慧",
        category="food",
        hours="11:00-20:30",
        duration=60,
        meal_slot="any",
        lon=121.47,
        lat=31.23,
    )
    snap = _snap([site, food], musts=("r-site", "r-food"))
    sol = _solve(snap)
    _ok(sol)
    plan = assemble(sol, snap)
    cards = [i for d in plan.days for i in d.items if i.name == "福和慧"]
    assert len(cards) == 1  # 顶餐卡：真餐厅即餐卡，不双渲染
    assert cards[0].poi_id == "p-resto"
    assert cards[0].location is not None
    assert cards[0].category == "food"
