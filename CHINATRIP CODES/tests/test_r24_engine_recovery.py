# -*- coding: utf-8 -*-
"""R24 tests (v2): monkeypatch entry.solve_trip (live helper lazy-imports it)."""

from types import SimpleNamespace

from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.trip_solver import entry, live
from app.services.trip_solver.entry import ENGINE_CPSAT, ENGINE_LEGACY


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


def _plan(*items):
    return ItineraryPlan(
        itinerary_id="t",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
    )


def _snapshot(candidates, musts_rids):
    return SimpleNamespace(
        candidates=[SimpleNamespace(cid=c, rid=r) for c, r in candidates],
        request=SimpleNamespace(musts=[SimpleNamespace(rid=r) for r in musts_rids]),
    )


def _placed(*cids):
    return SimpleNamespace(
        solution=SimpleNamespace(items=[SimpleNamespace(cid=c) for c in cids])
    )


def test_musts_all_placed_true():
    snap = _snapshot([("c1", "r1"), ("c2", "r2")], ["r1", "r2"])
    assert live._musts_all_placed(_placed("c1", "c2"), snap) is True


def test_musts_all_placed_false_when_one_missing():
    snap = _snapshot([("c1", "r1"), ("c2", "r2")], ["r1", "r2"])
    assert live._musts_all_placed(_placed("c1"), snap) is False


def test_musts_all_placed_skips_unbound_must():
    snap = _snapshot([("c1", "r1")], ["r1", "r-nocandidate"])
    assert live._musts_all_placed(_placed("c1"), snap) is True


def test_musts_all_placed_requires_one_resolved_must():
    snap = _snapshot([("c1", None)], [])
    assert live._musts_all_placed(_placed("c1"), snap) is False


def test_recover_retries_planless_cpsat_with_doubled_budget(monkeypatch):
    calls = []

    def fake_solve(snapshot, flag=None, budget_s=0):
        calls.append(budget_s)
        if len(calls) == 1:
            return SimpleNamespace(engine=ENGINE_CPSAT, plan=None, solution=None)
        return SimpleNamespace(
            engine=ENGINE_CPSAT, plan=_plan(_sight("c1")), solution=None
        )

    monkeypatch.setattr(entry, "solve_trip", fake_solve)
    first = fake_solve(None, budget_s=20.0)
    out = live._recover_outcome(None, first, budget_s=20.0)
    assert calls == [20.0, 40.0]
    assert out.plan is not None


def test_recover_no_retry_when_plan_exists(monkeypatch):
    calls = []

    def fake_solve(snapshot, flag=None, budget_s=0):
        calls.append(budget_s)
        return SimpleNamespace(
            engine=ENGINE_CPSAT, plan=_plan(_sight("c1")), solution=None
        )

    monkeypatch.setattr(entry, "solve_trip", fake_solve)
    first = fake_solve(None, budget_s=20.0)
    out = live._recover_outcome(None, first, budget_s=20.0)
    assert calls == [20.0]
    assert out is first


def test_recover_no_retry_for_legacy_outcome(monkeypatch):
    calls = []

    def fake_solve(snapshot, flag=None, budget_s=0):
        calls.append(budget_s)
        return SimpleNamespace(engine=ENGINE_LEGACY, plan=None, solution=None)

    monkeypatch.setattr(entry, "solve_trip", fake_solve)
    first = fake_solve(None, budget_s=20.0)
    out = live._recover_outcome(None, first, budget_s=20.0)
    assert calls == [20.0]
    assert out is first


def test_engine_declines_on_legacy_or_missing_plan():
    snap = _snapshot([("c1", "r1")], ["r1"])
    assert (
        live._engine_declines(SimpleNamespace(engine=ENGINE_LEGACY, plan=None), snap)
        is True
    )
    assert (
        live._engine_declines(SimpleNamespace(engine=ENGINE_CPSAT, plan=None), snap)
        is True
    )


def test_engine_declines_degenerate_but_musts_complete_passes():
    # 空日盘（degenerate）但必去全在场 → 放行（返回 False=不回落）。
    snap = _snapshot([("c1", "r1")], ["r1"])
    degenerate = _plan()  # 无 items 的日 → degenerate
    out = SimpleNamespace(engine=ENGINE_CPSAT, plan=degenerate)
    out.solution = _placed("c1").solution
    assert live._engine_declines(out, snap) is False


def test_engine_declines_degenerate_with_missing_must():
    snap = _snapshot([("c1", "r1")], ["r1"])
    degenerate = _plan()
    out = SimpleNamespace(engine=ENGINE_CPSAT, plan=degenerate)
    out.solution = _placed().solution
    assert live._engine_declines(out, snap) is True


def test_engine_serves_healthy_plan():
    snap = _snapshot([("c1", "r1")], ["r1"])
    out = SimpleNamespace(engine=ENGINE_CPSAT, plan=_plan(_sight("c1")))
    out.solution = _placed("c1").solution
    assert live._engine_declines(out, snap) is False
