# -*- coding: utf-8 -*-
"""R21 (2026-11-23, Tiananmen -> Palace 10:58 hole) regression pair.

1) tier-4 makespan prices interior idle gaps: sum(start) joined the tier,
   because day_end alone is blind to holes BETWEEN cards and trip-scale
   tier-4 solves are dtime-truncated FEASIBLE (never proven optimal; live
   wall_capped), so hole-y schedules landed in sessions nondeterministically
   (Tiananmen ends 08:46 -> Palace opens 10:58, a 132-minute unexplained gap
   the 30-minute bridge card made glaring).
2) the edit seam materializes the raw solve schedule and (unlike the
   generation path, solve_trip->assemble->compact_days since 7c2300a) never
   compacted it; an edit therefore re-stored raw hole-y schedules. The edit
   path now compacts before the plan is stored.
"""

from __future__ import annotations

from app.services.trip_solver.inputs.travel import haversine_km
from app.services.trip_solver.model.c01_c04 import _taxi_gap_minutes
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TripRequest,
)


def _gap(lon_a, lat_a, lon_b, lat_b):
    return _taxi_gap_minutes(haversine_km(lon_a, lat_a, lon_b, lat_b))


def _three_musts_snapshot():
    a = CandidateItem(
        cid="c1",
        name="Square",
        poi_id="P1",
        kind="requested",
        rid="r1",
        category="attraction",
        opening_hours="08:30-20:30",
        suggested_duration_min=90,
        lon=116.400,
        lat=39.910,
    )
    b = CandidateItem(
        cid="c2",
        name="Palace",
        poi_id="P2",
        kind="requested",
        rid="r2",
        category="museum",
        opening_hours="08:30-17:00",
        suggested_duration_min=240,
        lon=116.410,
        lat=39.930,
    )
    c = CandidateItem(
        cid="c3",
        name="Evening Park",
        poi_id="P3",
        kind="requested",
        rid="r3",
        category="park",
        opening_hours="16:30-21:00",
        suggested_duration_min=60,
        lon=116.420,
        lat=39.940,
    )
    return FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=1,
            cities=("Beijing",),
            musts=(
                RequestedItem(rid="r1", name="Square", poi_id="P1"),
                RequestedItem(rid="r2", name="Palace", poi_id="P2"),
                RequestedItem(rid="r3", name="Evening Park", poi_id="P3"),
            ),
        ),
        candidates=(a, b, c),
        source="synthetic",
    )


def test_tier4_prices_interior_gap_chain_packed():
    from app.services.trip_solver.inputs.enrich import enrich

    # The model itself forbids packing tighter than the 2026-11-03
    # morning single-point gate (MORNING_END = 12:00, at most one counted
    # card before noon per day; sunrise/pins exempt) and each card's own
    # window/travel floors. With sum(start) pricing every card must now
    # sit exactly at its model-earliest feasible start (packed chain),
    # never at an unexplained interior slack like the live 08:46 -> 10:58.
    from app.services.trip_solver.model.c09_c16 import MORNING_END
    from app.services.trip_solver.model.solve import solve_snapshot

    sol = solve_snapshot(enrich(_three_musts_snapshot()), budget_s=3.0)
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    assert not sol.unplaced
    items = {i.cid: (i.day, i.start_min, i.end_min) for i in sol.items}
    assert set(items) == {"c1", "c2", "c3"}
    (_day_a, s_a, e_a) = items["c1"]
    (day_b, s_b, e_b) = items["c2"]
    (day_c, s_c, _e_c) = items["c3"]
    assert day_b == day_c == 1
    gap_ab = _gap(116.400, 39.910, 116.410, 39.930)
    gap_bc = _gap(116.410, 39.930, 116.420, 39.940)
    # c2 may not take a second morning slot (c1 took it) but must sit at
    # that exact model-earliest boundary -- no slack above it
    assert s_b == max(e_a + gap_ab, MORNING_END)
    assert s_c == max(e_b + gap_bc, 16 * 60 + 30)


def test_edit_path_compacts_materialized_plan(monkeypatch):
    """Wiring guard: the edit seam must compact the materialized plan before
    it reaches the session (raw solve schedules must never be stored)."""
    import app.services.trip_solver.assembly.materialize as mat
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import (
        edit_session_via_trip_solver,
        replan_session_via_trip_solver,
    )
    from app.services.trip_solver.shadow.replay import SnapshotStore

    calls = {"n": 0}
    real_compact = mat.compact_days

    def spy(plan, snapshot):
        calls["n"] += 1
        return real_compact(plan, snapshot)

    monkeypatch.setattr(mat, "compact_days", spy)
    monkeypatch.setenv("TRIP_SOLVER", "cpsat")

    store = SnapshotStore(
        [
            CandidateItem(
                cid="p%d" % i,
                name=name,
                poi_id="poi_%d" % i,
                city="上海",
                category=cat,
                tier=tier,
                lon=121.47 + i * 0.008,
                lat=31.23,
                opening_hours="09:00-18:00",
                suggested_duration_min=90,
            )
            for i, (name, cat, tier) in enumerate(
                [
                    ("外滩", "sight", 1),
                    ("豫园", "sight", 2),
                    ("南京路步行街", "citywalk", 6),
                    ("静安寺", "temple", 3),
                    ("复兴公园", "park", 5),
                    ("上海美术馆", "art", 4),
                ]
            )
        ]
    )
    session = PlanSession(
        session_id="sess-r21",
        device_id="de-r21",
        cities=["上海"],
        days=2,
        start_date="2026-11-25",
        musts=["外滩", "豫园"],
        preferences="",
    )
    out = replan_session_via_trip_solver(session, store=store)
    assert out is not None and out.engine == "cpsat" and session.plan is not None
    seated = [
        it
        for d in session.plan.days
        for it in d.items
        if (it.category or "") not in ("food", "hotel")
        and not str(it.item_id or "").startswith("leg-bridge-")
    ]
    assert seated, "replan must seat cards"
    moved = seated[0]
    target_day = 2 if moved.day == 1 else 1
    new_plan, outcome = edit_session_via_trip_solver(
        session,
        store=store,
        ops=[{"kind": "move", "name": moved.name, "day": target_day}],
    )
    assert new_plan is not None, "engine edit must serve on native plan"
    # R21: the edit path compacted before storing (generation always did)
    assert calls["n"] >= 1, calls
