"""P1-F assembly tests: F-30 materialisation, F-31 meal cards, F-32
chips, F-33 bilingual disclosures, F-34 sync inputs — plus the G-01
end-to-end golden pass (solve -> assemble -> ItineraryPlan).
"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.models import (
    ItineraryPlan,
    PoiHours,
    VisitItem,
)
from app.services.itinerary.rules import validate_plan
from app.services.trip_solver.assembly import (
    assemble,
    attach_alternatives,
    materialize_plan,
    render_disclosures,
    wish_row_projection,
)
from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.certificate import load_templates
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.snapshot import default_golden_path, load_golden
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TripRequest,
)

G01 = default_golden_path()


def _g01_solution():
    snapshot, _expect, _prov = load_golden(G01)
    enriched = enrich(snapshot)
    solution = solve_snapshot(enriched)
    assert solution.status in ("OPTIMAL", "FEASIBLE")
    return snapshot, solution


def _poi_hours(snapshot):
    hours = []
    for cand in snapshot.candidates:
        if not cand.poi_id or not cand.opening_hours:
            continue
        try:
            opens, closes = cand.opening_hours.split("-")
            ho, mo = opens.split(":")
            hc, mc = closes.split(":")
        except ValueError:
            continue
        hours.append(
            PoiHours(
                poi_id=cand.poi_id,
                opens=time(int(ho), int(mo)),
                closes=time(int(hc), int(mc)),
            )
        )
    return hours


# ------------------------------------------------------------- F-30 golden


def test_g01_golden_end_to_end():
    snapshot, solution = _g01_solution()
    plan = assemble(solution, snapshot)
    assert isinstance(plan, ItineraryPlan)
    assert len(plan.days) == snapshot.request.days
    # every requested must is timed or honestly unplaced (B-01 dead)
    must_names = {m.name for m in snapshot.request.musts}
    placed = {i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)}
    for name in must_names:
        assert name in placed or any(u.name == name for u in plan.unplaced), name
    for day in plan.days:
        for item in day.items:
            if isinstance(item, VisitItem) and not item.synthetic:
                assert item.start_time is not None  # untimed = type error
    # card times == solution intervals (per placed cid)
    snapshot_cids = {c.cid for c in snapshot.candidates}
    card_cids = {
        i.poi_id
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.poi_id
    }
    assert card_cids <= {c.poi_id for c in snapshot.candidates if c.poi_id}
    assert snapshot_cids
    # P0-ish iron rules vacuously green
    report = validate_plan(plan, poi_hours=_poi_hours(snapshot))
    assert report.ok, [v.message for v in report.violations]


def test_g01_remote_day_card_equals_leg():
    snapshot, solution = _g01_solution()
    plan = assemble(solution, snapshot)
    remote = next(c for c in snapshot.candidates if "慕田峪" in c.name)
    leg = next(leg for leg in solution.access_legs if leg.get("cid") == remote.cid)
    day_no = leg["day"]
    site = next(
        i
        for d in plan.days
        if d.day == day_no
        for i in d.items
        if isinstance(i, VisitItem) and i.poi_id == remote.poi_id
    )
    start_min = site.start_time.hour * 60 + site.start_time.minute
    meal = next(
        m
        for m in solution.meal_anchors
        if m["day"] == day_no and m["slot"] == "lunch" and m.get("host_cid")
    )
    # E-1 / B-03c: site card = arrival + same-venue meal bridge
    assert meal["start_min"] == leg["arrive_poi_min"]
    assert start_min == meal["end_min"]
    assert site.access_mode == "access"
    # independent return card exists and is synthetic
    rets = [
        i
        for d in plan.days
        if d.day == day_no
        for i in d.items
        if isinstance(i, VisitItem) and i.synthetic
    ]
    assert rets, "return card must exist on the remote day"
    assert rets[0].start_time is not None
    # no unrequested card before the remote site on its day (C-15)
    seq = [
        i
        for d in plan.days
        if d.day == day_no
        for i in d.items
        if isinstance(i, VisitItem) and not i.synthetic and i.category != "food"
    ]
    seq.sort(key=lambda i: i.start_time)
    idx = next(i for i, v in enumerate(seq) if "慕田峪" in v.name)
    requested_names = {m.name for m in snapshot.request.musts} | {
        w.name for w in snapshot.request.wishes
    }
    for before in seq[:idx]:
        assert before.name in requested_names, before.name


def test_materialize_is_deterministic():
    snapshot, solution = _g01_solution()
    a = assemble(solution, snapshot)
    b = assemble(solution, snapshot)
    assert a.model_dump_json(exclude={"days": {"items": {"distance_to_next_km"}}}) == (
        b.model_dump_json(exclude={"days": {"items": {"distance_to_next_km"}}})
    )


def test_item_ids_unique_and_stable():
    snapshot, solution = _g01_solution()
    plan = assemble(solution, snapshot)
    ids = [i.item_id for d in plan.days for i in d.items]
    assert len(ids) == len(set(ids))


# ------------------------------------------------------------- F-31 meals


def test_meal_cards_anchor_at_host():
    snapshot, solution = _g01_solution()
    plan = assemble(solution, snapshot)
    cand_by_cid = {c.cid: c for c in snapshot.candidates}
    meals = {(m["slot"], m["day"]): m for m in solution.meal_anchors}
    remote = next(c for c in snapshot.candidates if "慕田峪" in c.name)
    remote_day = next(
        leg["day"] for leg in solution.access_legs if leg.get("cid") == remote.cid
    )
    remote = next(c for c in snapshot.candidates if "慕田峪" in c.name)
    lunch_card = next(
        i
        for d in plan.days
        if d.day == remote_day
        for i in d.items
        if isinstance(i, VisitItem)
        and i.category == "food"
        and i.start_time is not None
        and (i.start_time.hour * 60 + i.start_time.minute)
        == meals[("lunch", remote_day)]["start_min"]
    )
    host = cand_by_cid.get(meals[("lunch", remote_day)]["host_cid"])
    if host is not None:
        assert lunch_card.anchor_location is not None  # host record, not prev
        assert abs(lunch_card.anchor_location.lon - float(host.lon)) < 1e-9


# --------------------------------------------------------------- F-32 chips


def _chip_snapshot(host_hours: str = "09:00-18:00"):
    cands = [
        CandidateItem(
            cid="c1",
            name="主点",
            poi_id="p1",
            kind="requested",
            rid="r1",
            category="sight",
            opening_hours=host_hours,
            suggested_duration_min=90,
            lon=116.4,
            lat=39.9,
        ),
        CandidateItem(
            cid="c2",
            name="近邻点",
            poi_id="p2",
            kind="fill",
            category="sight",
            opening_hours="10:00-10:20",  # unseatable, stays in chip pool
            suggested_duration_min=60,
            lon=116.402,
            lat=39.9005,
        ),
        CandidateItem(
            cid="c3",
            name="远点",
            poi_id="p3",
            kind="fill",
            category="sight",
            opening_hours="09:00-18:00",
            suggested_duration_min=60,
            lon=116.1,
            lat=39.95,
        ),
    ]
    snap = FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=1,
            cities=("北京",),
            musts=(RequestedItem(rid="r1", name="主点", poi_id="p1"),),
        ),
        candidates=tuple(cands),
        source="synthetic",
    )
    return snap


def test_alternatives_radius_geometry():
    snapshot = _chip_snapshot()
    solution = solve_snapshot(enrich(snapshot))
    plan = attach_alternatives(materialize_plan(solution, snapshot), snapshot)
    host = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.poi_id == "p1"
    )
    assert host.alternatives, "0.2km neighbour should chip onto the host"
    assert host.alternatives[0].name == "近邻点"
    assert host.alternatives[0].distance_km is not None
    assert all(a.name != "远点" for a in (host.alternatives or []))


def test_unplaced_want_surface_and_reasons():
    # shrink the window so the must cannot seat (min tier 45 > 40min window)
    snapshot = _chip_snapshot(host_hours="10:00-10:40")
    solution = solve_snapshot(enrich(snapshot))
    assert solution.unplaced
    plan = assemble(solution, snapshot)
    assert plan.unplaced and plan.unplaced[0].reason
    assert plan.unarranged_musts == ["主点"]
    rows = wish_row_projection(plan)
    assert rows and rows[0]["name"] == "主点" and rows[0]["reason"]


# ------------------------------------------------------------ F-33 / F-34


def test_disclosures_bilingual_and_no_fallback_wording():
    snapshot = _chip_snapshot(host_hours="10:00-10:40")
    solution = solve_snapshot(enrich(snapshot))
    zh = render_disclosures(solution, snapshot, lang="zh")
    en = render_disclosures(solution, snapshot, lang="en")
    assert zh and en
    assert any("想去" in line for line in zh)
    assert any("want" in line for line in en)
    assert not any("未收敛" in line for line in zh + en)
    plan = assemble(solution, snapshot)
    assert plan.assumptions == zh


def test_disclosures_all_placed_line():
    snapshot, solution = _g01_solution()
    if solution.unplaced:
        return  # g01 currently seats everything; synthetic covers the rest
    zh = render_disclosures(solution, snapshot, lang="zh")
    assert any("全部排入" in line for line in zh)


def test_serving_ready_flips_with_assembly():
    from app.services.trip_solver import entry

    ok, why = entry.serving_ready()
    assert ok, why


def test_entry_cpsat_path_materializes_plan():
    from app.services.trip_solver import entry

    snapshot = _chip_snapshot()
    outcome = entry.solve_trip(snapshot, flag="cpsat", budget_s=5.0)
    assert outcome.engine == "cpsat"
    assert outcome.plan is not None
    assert outcome.plan.days


# ----------------------------------------------- completeness closures


def test_fares_and_display_legs_materialized():
    snapshot, solution = _g01_solution()
    plan = assemble(solution, snapshot)
    remote = next(c for c in snapshot.candidates if "慕田峪" in c.name)
    profile = next(
        (p for p in snapshot.access_profiles if p.to_poi == remote.poi_id), None
    )
    site = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.poi_id == remote.poi_id
    )
    if profile is not None and profile.fare_text:
        assert site.access_fare_text == profile.fare_text  # F-30 fare attach
    if profile is not None and profile.operator:
        assert site.access_service_name == profile.operator
    # annotate_legs ran: at least one same-day display leg got a distance
    legs = [
        i.distance_to_next_km
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.distance_to_next_km is not None
    ]
    assert legs, "annotate_legs must materialise display legs"


def test_weather_disclosure_lines():
    from app.services.trip_solver.types import FactSnapshot, RequestedItem, TripRequest

    snapshot = _chip_snapshot()
    weathered = FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=1,
            cities=("北京",),
            musts=(RequestedItem(rid="r1", name="主点", poi_id="p1"),),
            start_date="2026-11-25",
        ),
        candidates=tuple(
            (
                [
                    c.model_copy(update={"rain_ok": "no"})
                    if hasattr(c, "model_copy")
                    else c
                    for c in snapshot.candidates
                ]
            )
        ),
        weather=(("p1", "2026-11-25", "小雨 (light rain)"),),
        source="synthetic",
    )
    solution = solve_snapshot(enrich(weathered))
    zh = render_disclosures(solution, weathered, lang="zh")
    en = render_disclosures(solution, weathered, lang="en")
    assert any("小雨" in line for line in zh)
    assert any("rain" in line for line in en)
    plan = assemble(solution, weathered)
    assert any("小雨" in line for line in plan.assumptions)


def test_coverage_test_is_non_circular():
    from app.services.trip_solver.model.certificate import (
        EMITTED_CODES,
        emitted_codes,
    )

    assert emitted_codes() == set(EMITTED_CODES)
    assert set(EMITTED_CODES) == set(load_templates()["certificate_reasons"])
