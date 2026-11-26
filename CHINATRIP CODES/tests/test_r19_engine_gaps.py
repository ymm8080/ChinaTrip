# -*- coding: utf-8 -*-
"""R19 regression tests: CP-SAT transition gap fixes.

1. access-chain render cards (access-out- / access-return- / taxi-board- /
   leg-bridge-) are immune in the filler, geo-clustering and response-strip
   layers;
2. site-confirm alias matching picks the canonical candidate and discloses
   unmatched names instead of dropping them silently;
3. chosen shuttle times ride into the rebuild snapshot (and stay out of
   snapshot_hash so corpus replay cannot drift).
"""

from types import SimpleNamespace

from app.services.agent.plan import _is_leg_render_card, _reunite_tight_kin
from app.services.itinerary.hotfix_1117 import _is_filler
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem


def _visit(
    item_id,
    name,
    city="Beijing",
    day=1,
    cat="sight",
    st=None,
    en=None,
    lon=None,
    lat=None,
):
    return VisitItem(
        item_id=item_id,
        name=name,
        category=cat,
        city=city,
        day=day,
        start_time=st,
        end_time=en,
        duration_minutes=90,
        location=GeoPoint(lon=lon, lat=lat) if lon is not None else None,
    )


def test_is_filler_exempts_access_chain_cards():
    for iid in (
        "access-out-v1",
        "access-return-v1",
        "access-return-meal-dinner-1",
        "taxi-board-v1",
        "leg-bridge-d1-1",
    ):
        card = _visit(iid, "x", cat="transfer")
        assert _is_filler(card) is False, iid
        assert _is_leg_render_card(card) is True, iid
    plain = _visit("v1", "Some Sight")
    assert _is_filler(plain) is True


def test_reunite_tight_kin_keeps_outbound_card_on_remote_day():
    square = _visit("v1", "Square", day=1, st=None, en=None, lon=116.397, lat=39.909)
    square.start_time = None
    park = _visit("v2", "Park", day=1, lon=116.400, lat=39.925)
    outbound = _visit(
        "access-out-v9",
        "Outbound shuttle",
        day=2,
        cat="transfer",
        lon=116.398,
        lat=39.899,
    )
    from datetime import time

    outbound.start_time = time(8, 30)
    outbound.end_time = time(10, 8)
    wall = _visit("v9", "Great Wall", day=2, st=None, en=None, lon=116.560, lat=40.430)
    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["Beijing"],
        days=[
            DayPlan(day=1, base_city="Beijing", items=[square, park]),
            DayPlan(day=2, base_city="Beijing", items=[outbound, wall]),
        ],
    )
    _reunite_tight_kin(plan)
    day2_ids = [i.item_id for i in plan.days[1].items]
    assert "access-out-v9" in day2_ids
    kept = next(i for i in plan.days[1].items if i.item_id == "access-out-v9")
    assert kept.start_time is not None and kept.start_time.hour == 8
    assert [i.item_id for i in plan.days[0].items] == ["v1", "v2"]


def test_strip_untimed_items_keeps_access_chain_cards():
    from app.api.plan import _strip_untimed_items

    outbound = _visit("access-out-v1", "Outbound shuttle", cat="transfer")
    plain = _visit("v2", "Plain Sight")
    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["Beijing"],
        days=[DayPlan(day=1, base_city="Beijing", items=[outbound, plain])],
    )
    out = _strip_untimed_items(plan)
    ids = [i.item_id for i in out.days[0].items]
    assert "access-out-v1" in ids
    assert "v2" not in ids
    assert [u.name for u in out.unplaced] == ["Plain Sight"]
    assert all(u.reason == "untimed_demoted" for u in out.unplaced)


def test_match_picked_sites_alias_and_unmatched():
    from app.services.trip_orchestrator.rounds import _match_picked_sites

    sites = ["Square", "Palace Museum Precinct", "Great Wall"]
    picked, unmatched = _match_picked_sites(sites, ["Square", "Palace"])
    assert picked == ["Square", "Palace Museum Precinct"]
    assert unmatched == []
    picked, unmatched = _match_picked_sites(sites, ["Palace Museum Precinct"])
    assert picked == ["Palace Museum Precinct"]
    picked, unmatched = _match_picked_sites(sites, ["Nowhere XYZ"])
    assert picked == []
    assert unmatched == ["Nowhere XYZ"]
    # single-char guard: no substring aliasing
    picked, unmatched = _match_picked_sites(["abc site"], ["a"])
    assert picked == []
    assert unmatched == ["a"]


def test_overlay_chosen_departures_and_hash_stability():
    from app.services.trip_solver.live import _overlay_chosen_departures
    from app.services.trip_solver.snapshot import snapshot_hash
    from app.services.trip_solver.types import CandidateItem, FactSnapshot, TripRequest

    snapshot = FactSnapshot(
        schema_version=1,
        request=TripRequest(days=2, cities=("Beijing",)),
        candidates=(
            CandidateItem(cid="c1", name="Great Wall", poi_id="P1", kind="requested"),
            CandidateItem(cid="c2", name="Square", poi_id="P2"),
        ),
    )
    wall = _visit("v1", "Great Wall", day=1)
    wall.poi_id = "P1"
    wall.access_chosen_depart = "09:30"
    wall.access_chosen_return = "15:30"
    session = SimpleNamespace(
        plan=ItineraryPlan(
            itinerary_id="t",
            cities=["Beijing"],
            days=[DayPlan(day=1, base_city="Beijing", items=[wall])],
        )
    )
    base_hash = snapshot_hash(snapshot)
    out = _overlay_chosen_departures(snapshot, session)
    by_cid = {c.cid: c for c in out.candidates}
    assert by_cid["c1"].chosen_depart == "09:30"
    assert by_cid["c1"].chosen_return == "15:30"
    assert by_cid["c2"].chosen_depart is None
    # chosen is a live-session fact: excluded from the determinism hash
    assert snapshot_hash(out) == base_hash
    # idempotent
    again = _overlay_chosen_departures(out, session)
    assert [c.chosen_depart for c in again.candidates] == ["09:30", None]


def test_dedupe_plan_assumptions_order_preserving_and_non_mutating():
    from app.api.plan import _dedupe_plan_assumptions

    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["Beijing"],
        days=[],
        assumptions=["a", "b", "a", "c", "b"],
    )
    out = _dedupe_plan_assumptions(plan)
    assert out.assumptions == ["a", "b", "c"]
    assert plan.assumptions == ["a", "b", "a", "c", "b"]
