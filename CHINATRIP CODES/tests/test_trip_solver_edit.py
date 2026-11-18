"""P4 edit re-solve tests (F-50/F-51, M12/Q7).

User edits are facts (retime → immovable C-04 pin), everything else
re-solves freely with the previous solution as hint; edits stay inside the
800 ms envelope on corpus snapshots and are deterministic; overruns keep
the current plan + the 「重排中」 disclosure.
"""

from __future__ import annotations

import os

from app.services.trip_solver.edit import (
    EDIT_BUDGET_SECONDS,
    DiffOp,
    edit_resolve,
)
from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.shadow.corpus import default_corpus_dir, load_scenario
from app.services.trip_solver.snapshot import load_golden


def _g01():
    return load_golden(os.path.join(default_corpus_dir(), "g01.json"))[0]


def _base_solution(snapshot):
    return solve_snapshot(enrich(snapshot), budget_s=3.0)


def test_retime_creates_immovable_user_pin():
    snap = _g01()
    prev = _base_solution(snap)
    out = edit_resolve(
        snap,
        prev,
        [DiffOp(kind="retime", cid="c7", day=2, start_min=9 * 60)],
    )
    assert out.status == "OPTIMAL"
    yihy = next(i for i in out.solution.items if i.cid == "c7")
    assert (yihy.day, yihy.start_min) == (2, 9 * 60)  # immovable (iron rule 19)
    assert out.user_pins == [
        {"cid": "c7", "day": 2, "start_min": 540, "source": "user"}
    ]  # F-51 provenance
    assert out.ops_applied and out.ops_applied[0].kind == "retime"


def test_move_places_candidate_on_requested_day():
    snap = _g01()
    prev = _base_solution(snap)
    moved = next(i for i in prev.items if i.cid == "c1")
    target_day = 2 if moved.day == 1 else 1
    out = edit_resolve(snap, prev, [DiffOp(kind="move", cid="c1", day=target_day)])
    c1 = next(i for i in out.solution.items if i.cid == "c1")
    assert c1.day == target_day


def test_delete_fill_removes_and_delete_must_drops_obligation():
    snap = _g01()
    prev = _base_solution(snap)
    out = edit_resolve(snap, prev, [DiffOp(kind="delete", cid="c2")])  # 老舍茶馆 fill
    assert not any(i.cid == "c2" for i in out.solution.items)
    # deleting a requested must removes its unplaced obligation entirely
    out2 = edit_resolve(snap, prev, [DiffOp(kind="delete", cid="c5")])  # 天坛 r4
    assert not any(u.get("name") == "天坛" for u in out2.solution.unplaced)
    assert not any(i.cid == "c5" for i in out2.solution.items)


def test_duration_op_clamps_into_tier():
    snap = _g01()
    prev = _base_solution(snap)
    low, typ, high, _ = enrich(snap).tiers["c7"]  # 颐和园 tier [low, 300]
    target = min(high, max(low, 999))  # op asks 999 → clamped to tier high
    out = edit_resolve(
        snap, prev, [DiffOp(kind="duration", cid="c7", duration_min=999)]
    )
    yihy = next(i for i in out.solution.items if i.cid == "c7")
    assert yihy.end_min - yihy.start_min == target  # clamped, never beyond tier


def test_edit_resolve_is_deterministic():
    snap = _g01()
    prev = _base_solution(snap)
    ops = [DiffOp(kind="retime", cid="c1", day=1, start_min=430)]
    a = edit_resolve(snap, prev, list(ops))
    b = edit_resolve(snap, prev, list(ops))
    assert [(i.cid, i.day, i.start_min) for i in a.solution.items] == [
        (i.cid, i.day, i.start_min) for i in b.solution.items
    ]


def test_edit_within_q7_envelope_on_corpus():
    # corpus-scale edits must land inside the 800ms hint envelope
    for stem in ("g01", "g11_trip_scale"):
        scenario = load_scenario(os.path.join(default_corpus_dir(), "%s.json" % stem))
        prev = _base_solution(scenario.snapshot)
        out = edit_resolve(
            scenario.snapshot,
            prev,
            [DiffOp(kind="retime", cid="c1", day=1, start_min=430)],
        )
        assert out.within_edit_budget, (stem, out.wall_ms)


def test_overrun_keeps_plan_and_discloses():
    snap = _g01()
    prev = _base_solution(snap)

    def _slow(*args, **kwargs):  # force the M12 branch deterministically
        import time as _t

        _t.sleep(EDIT_BUDGET_SECONDS + 0.05)
        return solve_snapshot(enrich(snap), budget_s=3.0)

    out = edit_resolve(snap, prev, [DiffOp(kind="move", cid="c2", day=2)], _solve=_slow)
    assert out.status == "RETIMING"
    assert out.solution is prev  # current plan kept
    assert out.disclosure and "重排中" in out.disclosure["zh"]
    assert out.user_pins == []


def test_reopen_preserves_user_pins():
    # B-09 reopen shape: a no-op re-solve keeps user pins byte-identical
    snap = _g01()
    prev = _base_solution(snap)
    pinned = edit_resolve(
        snap, prev, [DiffOp(kind="retime", cid="c7", day=2, start_min=9 * 60)]
    )
    again = edit_resolve(
        snap,
        pinned.solution,
        [DiffOp(kind="retime", cid="c7", day=2, start_min=9 * 60)],
    )
    a = next(i for i in again.solution.items if i.cid == "c7")
    assert (a.day, a.start_min) == (2, 9 * 60)
