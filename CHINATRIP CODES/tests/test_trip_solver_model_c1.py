"""P1-C1 model-core tests: tiny synthetic solves, B-01 construction proof
(untimed requested is unrepresentable), pins immovable, entry caps, travel
disjunction, closed weekdays, G-01 integration smoke.

Building synthetic snapshots inline keeps each case self-contained; the
G-01 fixture provides the real-data integration check.
"""

from __future__ import annotations

from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.c01_c04 import closed_weekdays
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.snapshot import (
    default_golden_path,
    load_golden,
)
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TravelLeg,
    TripRequest,
)

G01 = default_golden_path()


def snap(
    candidates: list[CandidateItem],
    musts: list[RequestedItem],
    *,
    days: int = 1,
    start_date: str | None = None,
    travel: list[TravelLeg] | None = None,
    pins: tuple = (),
) -> FactSnapshot:
    return FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=days,
            cities=("北京",),
            start_date=start_date,
            musts=tuple(musts),
            pins=pins,
        ),
        candidates=tuple(candidates),
        travel=tuple(travel or ()),
        source="synthetic",
    )


def cand(
    cid,
    name,
    hours,
    dur,
    *,
    category="attraction",
    tier=1,
    poi_id=None,
    lon=None,
    lat=None,
    rid=None,
):
    return CandidateItem(
        cid=cid,
        name=name,
        poi_id=poi_id,
        kind="requested" if rid else "fill",
        rid=rid,
        category=category,
        tier=tier,
        opening_hours=hours,
        suggested_duration_min=dur,
        lon=lon,
        lat=lat,
    )


# ---------- tiny synthetic solve ----------


def test_two_musts_one_day_ordered_with_travel_gap():
    a = cand(
        "c1", "甲", "09:00-17:00", 60, poi_id="p1", lon=116.40, lat=39.90, rid="r1"
    )
    b = cand(
        "c2", "乙", "09:00-17:00", 60, poi_id="p2", lon=116.42, lat=39.92, rid="r2"
    )
    musts = [
        RequestedItem(rid="r1", name="甲", poi_id="p1"),
        RequestedItem(rid="r2", name="乙", poi_id="p2"),
    ]
    legs = [
        TravelLeg(from_key="p1", to_key="p2", minutes=30),
        TravelLeg(from_key="p2", to_key="p1", minutes=30),
    ]
    sol = solve_snapshot(enrich(snap([a, b], musts, travel=legs)))
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    placed = {it.cid: it for it in sol.items}
    assert set(placed) == {"c1", "c2"}
    first, second = sorted(placed.values(), key=lambda it: it.start_min)
    assert second.start_min - first.end_min >= 30  # C-03 travel respected


def test_requested_unplaceable_goes_to_unplaced_never_untimed():
    # even the tier minimum (60) cannot fit a 30-minute window → unplaced.
    a = cand("c1", "甲", "09:00-09:30", 120, poi_id="p1", rid="r1")
    must = RequestedItem(rid="r1", name="甲", poi_id="p1")
    sol = solve_snapshot(enrich(snap([a], [must])))
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    assert sol.items == []  # never an untimed card (B-01 construction)
    assert [u["rid"] for u in sol.unplaced] == ["r1"]
    # and every emitted item always carries concrete times
    for it in sol.items:
        assert it.start_min >= 0 and it.end_min > it.start_min


# ---------- C-04 pins ----------


def test_pin_is_immovable_exact_day_and_start():
    a = cand("c1", "甲", "09:00-17:00", 60, poi_id="p1", rid="r1")
    must = RequestedItem(rid="r1", name="甲", poi_id="p1")
    from app.services.trip_solver.types import FixedPin

    pin = (FixedPin(rid="r1", day=1, start_min=10 * 60),)
    sol = solve_snapshot(enrich(snap([a], [must], pins=pin)))
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    (it,) = sol.items
    assert it.start_min == 600 and it.day == 1


def test_two_pins_same_slot_is_infeasible_not_moved():
    a = cand("c1", "甲", "08:00-17:00", 120, poi_id="p1", rid="r1")
    b = cand("c2", "乙", "08:00-17:00", 120, poi_id="p2", rid="r2")
    musts = [
        RequestedItem(rid="r1", name="甲", poi_id="p1"),
        RequestedItem(rid="r2", name="乙", poi_id="p2"),
    ]
    from app.services.trip_solver.types import FixedPin

    pins = (
        FixedPin(rid="r1", day=1, start_min=600),
        FixedPin(rid="r2", day=1, start_min=630),
    )
    sol = solve_snapshot(enrich(snap([a, b], musts, pins=pins)))
    assert sol.status == "INFEASIBLE"  # pins never yield, no fallback


# ---------- C-02 caps ----------


def test_entry_cap_bounds_start():
    # window till 22:00, generic cap would be 990, big-site 930 (dur 120)
    a = cand("c1", "甲", "09:00-22:00", 120, poi_id="p1", category="museum", rid="r1")
    must = RequestedItem(rid="r1", name="甲", poi_id="p1")
    sol = solve_snapshot(enrich(snap([a], [must])))
    (it,) = sol.items
    assert it.start_min <= 930  # big-site cap 15:30 (F-12 semantics)


# ---------- C-01 closed weekday ----------


def test_closed_weekday_blocks_that_day():
    assert 0 in closed_weekdays("周一关闭(法定节假日除外),09:00-17:00")
    a = cand("c1", "甲", "周一关闭,09:00-17:00", 60, poi_id="p1", rid="r1")
    must = RequestedItem(rid="r1", name="甲", poi_id="p1")
    # 2026-11-23 is a Monday; two days → must land on day 2
    sol = solve_snapshot(enrich(snap([a], [must], days=2, start_date="2026-11-23")))
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    (it,) = sol.items
    assert it.day == 2


# ---------- G-01 integration smoke ----------


def test_g01_all_five_musts_place_within_windows_and_caps():
    snapshot, expect, _ = load_golden(G01)
    enriched = enrich(snapshot)
    sol = solve_snapshot(enriched)
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    placed = {it.cid: it for it in sol.items}
    must_cids = {c.cid for c in snapshot.candidates if c.kind == "requested"}
    # R12-H24/H18 后语料全排：远郊日=长城+老舍茶馆（≤120 小点回插
    # 余量位），城内日=升旗+故宫+颐和园+天坛+梵高（盖饭/晚带压缩
    # 就位）——五必去零弃排。
    assert must_cids <= set(placed), sol.unplaced
    assert sol.unplaced == []
    # every placement respects its window, cap and pairwise travel
    _bvt = {c.cid: (c.best_visit_time or "") for c in snapshot.candidates}
    for cid, it in placed.items():
        window = enriched.windows[cid]
        if window is not None:
            # R12-H11：升旗卡=晨锁带（锚=升旗真值/静态 06:30），
            # 不受 08:30 日始锚强制。
            _floor = 390 if _bvt.get(cid) == "sunrise" else 510
            assert it.start_min >= max(_floor, window[0]), cid
            assert it.end_min <= min(1260, window[1]), cid
        cap = enriched.caps[cid][0]
        if cap is not None:
            assert it.start_min <= cap, cid
    by_day: dict[int, list] = {}
    for it in sol.items:
        by_day.setdefault(it.day, []).append(it)
    for day, items in by_day.items():
        items.sort(key=lambda i: i.start_min)
        for x, y in zip(items, items[1:]):
            assert y.start_min >= x.end_min  # no overlap (travel gaps ≥ 0)
    # determinism red line (F-41): same snapshot, byte-identical plan
    sol2 = solve_snapshot(enriched)
    assert [(i.cid, i.day, i.start_min, i.end_min) for i in sol.items] == [
        (i.cid, i.day, i.start_min, i.end_min) for i in sol2.items
    ]
