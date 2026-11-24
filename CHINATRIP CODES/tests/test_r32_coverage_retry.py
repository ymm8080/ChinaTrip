# -*- coding: utf-8 -*-
"""R32: a time-capped suboptimal coverage must not be delivered as final.

solve.py locks the tier-① coverage value with an equality as soon as a
FEASIBLE incumbent exists. With a short wall budget that incumbent can leave
must-visits unplaced even though a slightly longer search places all of them
(live repro: 3s -> 5 unplaced, 6s -> 0). The delivery guard now re-solves with
a larger budget whenever a healthy-shaped plan still loses a must.
"""

from types import SimpleNamespace

from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.trip_solver import entry, live
from app.services.trip_solver.entry import ENGINE_CPSAT


def _sight(cid):
    return VisitItem(
        item_id=cid,
        name=cid,
        category="sight",
        city="北京",
        day=1,
        duration_minutes=90,
        location=GeoPoint(lon=116.4, lat=39.9),
    )


def _plan(*cids):
    return ItineraryPlan(
        itinerary_id="t32",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[_sight(c) for c in cids])],
    )


def _snapshot(n=2, days=1):
    return SimpleNamespace(
        candidates=[SimpleNamespace(cid=f"c{i}", rid=f"r{i}") for i in range(1, n + 1)],
        request=SimpleNamespace(
            musts=[SimpleNamespace(rid=f"r{i}") for i in range(1, n + 1)],
            days=days,
        ),
    )


def _outcome(*cids, days=1):
    return SimpleNamespace(
        engine=ENGINE_CPSAT,
        plan=_plan(*cids),
        solution=SimpleNamespace(items=[SimpleNamespace(cid=c) for c in cids]),
        days=days,
    )


def test_uncovered_must_count():
    snap = _snapshot()
    assert live._uncovered_must_count(_outcome("c1", "c2"), snap) == 0
    assert (
        live._uncovered_must_count(
            _outcome(
                "c1",
            ),
            snap,
        )
        == 1
    )
    assert live._uncovered_must_count(_outcome(), snap) == 2
    assert live._uncovered_must_count(SimpleNamespace(solution=None), snap) == -1


def test_recover_resolves_when_healthy_plan_loses_a_must(monkeypatch):
    calls = []

    def fake_solve(snapshot, flag=None, budget_s=0):
        calls.append(budget_s)
        return _outcome("c1", "c2")  # retry finds the full coverage

    monkeypatch.setattr(entry, "solve_trip", fake_solve)
    snap = _snapshot()
    first = _outcome(
        "c1",
    )  # time-capped incumbent lost r2
    out = live._recover_outcome(snap, first, budget_s=3.0)
    assert calls == [12.0]  # max(3*3, 12) - not the 40s failure retry
    assert out is not first
    assert live._uncovered_must_count(out, snap) == 0


def test_recover_keeps_original_when_coverage_not_improved(monkeypatch):
    def fake_solve(snapshot, flag=None, budget_s=0):
        return _outcome("c2")  # still one must missing (different one)

    monkeypatch.setattr(entry, "solve_trip", fake_solve)
    snap = _snapshot()
    first = _outcome(
        "c1",
    )
    out = live._recover_outcome(snap, first, budget_s=3.0)
    assert out is first


def test_recover_keeps_original_when_solution_unknown(monkeypatch):
    # No solution object -> coverage cannot be judged; preserve legacy guard
    # behaviour (existing R24 contract).
    def fake_solve(snapshot, flag=None, budget_s=0):
        raise AssertionError("must not retry")

    monkeypatch.setattr(entry, "solve_trip", fake_solve)
    first = SimpleNamespace(
        engine=ENGINE_CPSAT,
        plan=_plan(
            "c1",
        ),
        solution=None,
    )
    out = live._recover_outcome(_snapshot(), first, budget_s=3.0)
    assert out is first


def test_recover_prefers_full_plan_even_if_retry_missing_unknown(monkeypatch):
    def fake_solve(snapshot, flag=None, budget_s=0):
        return SimpleNamespace(
            engine=ENGINE_CPSAT, plan=_plan("c1", "c2"), solution=None
        )

    monkeypatch.setattr(entry, "solve_trip", fake_solve)
    snap = _snapshot()
    first = _outcome(
        "c1",
    )
    out = live._recover_outcome(snap, first, budget_s=3.0)
    assert len(out.plan.days[0].items) == 2
