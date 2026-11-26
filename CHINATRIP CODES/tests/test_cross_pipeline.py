# -*- coding: utf-8 -*-
"""Cross-pipeline alignment tests (2026-11-18 ruling + legacy-fix parity)."""

import os

from app.services.trip_solver.edit import DiffOp, edit_resolve
from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.live import _mode_from_no, snapshot_from_request
from app.services.trip_solver.model.c05_c08 import arrival_floor_for
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.shadow.corpus import default_corpus_dir
from app.services.trip_solver.snapshot import load_golden


def _g01():
    return load_golden(os.path.join(default_corpus_dir(), "g01.json"))[0]


def _base(snapshot):
    return solve_snapshot(enrich(snapshot), budget_s=3.0)


# --- A) days op ----------------------------------------------------------------


def test_days_extend_adds_day_and_regresses_deterministically():
    snap = _g01()
    prev = _base(snap)
    out = edit_resolve(snap, prev, [DiffOp(kind="days", cid="", days=3)])
    assert out.solution.status in ("OPTIMAL", "FEASIBLE")
    days_used = {i.day for i in out.solution.items}
    assert days_used <= {1, 2, 3}
    again = edit_resolve(snap, prev, [DiffOp(kind="days", cid="", days=3)])
    assert [(i.day, i.start_min) for i in out.solution.items] == [
        (i.day, i.start_min) for i in again.solution.items
    ]


def test_days_shrink_surfaces_unplaced_never_silent():
    snap = _g01()  # 5 musts on 2 days
    prev = _base(snap)
    out = edit_resolve(snap, prev, [DiffOp(kind="days", cid="", days=1)])
    placed = [i for i in out.solution.items]
    names_placed = {i.cid for i in placed}
    must_cids = {c.cid for c in snap.candidates if c.rid}
    must_cids - names_placed
    # whatever didn't fit MUST surface as unplaced (B-01 semantics)
    all_names = {c.name for c in snap.candidates if c.rid}
    for u in out.solution.unplaced:
        assert u.get("name") in all_names
        assert u.get("reason")  # F-26 reason codes present


# --- B) mode-dependent buffers --------------------------------------------------


def test_buffer_ruling_train2h_plane2h5_default2h5():
    # 2026-11-18 用户拍板「火车 2h / 飞机 2.5h」；无模式地板 150
    assert arrival_floor_for("train") == 120
    assert arrival_floor_for("TRAIN") == 120
    assert arrival_floor_for("flight") == 150
    assert arrival_floor_for(None) == 150
    assert arrival_floor_for("bus") == 150


def test_mode_from_no_recognizes_train_and_flight():
    assert _mode_from_no("G1234") == "train"
    assert _mode_from_no("d2571") == "train"
    assert _mode_from_no("CA1832") == "flight"
    assert _mode_from_no("MU5137") == "flight"
    assert _mode_from_no("") is None
    assert _mode_from_no("随便") is None


def test_snapshot_carries_mode_from_numbers():
    from app.services.trip_solver.shadow.replay import SnapshotStore
    from app.services.trip_solver.types import CandidateItem

    store = SnapshotStore(
        [
            CandidateItem(
                cid="c1",
                name="外滩",
                poi_id="ct_上海_20",
                city="上海",
                category="sight",
                tier=1,
                lon=121.49,
                lat=31.23,
                opening_hours="09:00-21:00",
                suggested_duration_min=90,
            )
        ]
    )
    snap = snapshot_from_request(
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=[],
        store=store,
        arrival_time="15:00",
        arrival_no="G1234",
        departure_time="21:00",
        departure_no="CA1832",
    )
    assert snap.request.arrival_mode == "train"
    assert snap.request.departure_mode == "flight"


# --- C) seam INFEASIBLE disclosure ----------------------------------------------


def test_cpsat_no_plan_discloses_fallback(monkeypatch):
    from app.services.trip_solver import entry as entry_mod
    from app.services.trip_solver import live as live_mod

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")

    class _NoPlan:
        engine = "cpsat"
        plan = None
        fallback = False
        disclosures = []

    monkeypatch.setattr(entry_mod, "solve_trip", lambda *a, **kw: _NoPlan())
    # live imports solve_trip inside the function from .entry — patch there too
    session, outcome = live_mod.generate_session_via_trip_solver(
        device_id="t",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=[],
        store=_store_stub(),
    )
    assert session is None
    assert outcome.fallback is True
    assert outcome.disclosures and "现行引擎" in outcome.disclosures[0]["zh"]


def _store_stub():
    from app.services.trip_solver.shadow.replay import SnapshotStore
    from app.services.trip_solver.types import CandidateItem

    return SnapshotStore(
        [
            CandidateItem(
                cid="c1",
                name="外滩",
                poi_id="ct_上海_20",
                city="上海",
                category="sight",
                tier=1,
                lon=121.49,
                lat=31.23,
                opening_hours="09:00-21:00",
                suggested_duration_min=90,
            )
        ]
    )
