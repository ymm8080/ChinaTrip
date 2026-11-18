"""P3 flag-gated entry adapter tests (F-35/F-36/M8, code-first cutover-later).

The switch is verified at the contract level: flag resolution, shadow
sampling (M6), not-ready fallback (= the M8 rollback shape pre-P1-F),
fail-loud test mode, telemetry shape. No api seam exists until P1-F can
serve — these tests ARE the rollback verification the phases doc asks for.
"""

from __future__ import annotations

import pytest

from app.services.trip_solver import entry
from app.services.trip_solver.entry import (
    ENGINE_CPSAT,
    ENGINE_LEGACY,
    ENGINE_SHADOW,
    ENV_FLAG,
    ServingNotReady,
    should_sample,
    solve_trip,
)
from app.services.trip_solver.snapshot import load_golden
from app.services.trip_solver.telemetry import solve_telemetry
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    Solution,
    SolutionItem,
    TripRequest,
)


def _mini_snapshot() -> FactSnapshot:
    request = TripRequest(
        days=1,
        cities=("上海",),
        musts=(RequestedItem(rid="r1", name="东方明珠", poi_id="p1"),),
    )
    cand = CandidateItem(
        cid="c1",
        name="东方明珠",
        poi_id="p1",
        kind="requested",
        rid="r1",
        category="sight",
        tier=4,
        lon=121.4997,
        lat=31.2397,
        opening_hours="08:30-19:30",
        suggested_duration_min=90,
        city="上海",
    )
    return FactSnapshot(
        schema_version=1, request=request, candidates=(cand,), source="test"
    )


def _g02_snapshot() -> FactSnapshot:
    import os

    from app.services.trip_solver.shadow.corpus import default_corpus_dir

    path = os.path.join(default_corpus_dir(), "g02_tower_late_gate.json")
    snapshot, _expect, _prov = load_golden(path)
    return snapshot


# --- flag resolution ----------------------------------------------------------


def test_flag_resolution_default_env_and_invalid():
    assert entry.engine_flag({}) == ENGINE_LEGACY
    assert entry.engine_flag({ENV_FLAG: "cpsat"}) == ENGINE_CPSAT
    assert entry.engine_flag({ENV_FLAG: "SHADOW"}) == ENGINE_SHADOW
    assert entry.engine_flag({ENV_FLAG: "bogus"}) == ENGINE_LEGACY  # typo degrades
    assert entry.engine_flag({ENV_FLAG: " cpsat "}) == ENGINE_CPSAT


# --- legacy: pure passthrough, zero model work --------------------------------


def test_legacy_outcome_never_touches_the_model(monkeypatch):
    def _boom(*a, **kw):  # pragma: no cover - any model call is a bug here
        raise AssertionError("legacy flag must not run the model")

    monkeypatch.setattr(entry, "solve_snapshot", _boom)
    out = solve_trip(_mini_snapshot(), flag=ENGINE_LEGACY)
    assert out.engine == ENGINE_LEGACY and out.requested == ENGINE_LEGACY
    assert out.solution is None and out.telemetry is None
    assert out.fallback is False and out.disclosures == []


# --- cpsat pre-P1-F: not-ready fallback == the M8 rollback shape --------------


def test_cpsat_pre_p1f_falls_back_with_disclosure():
    out = solve_trip(_mini_snapshot(), flag=ENGINE_CPSAT)
    assert out.engine == ENGINE_LEGACY  # cascade serves
    assert out.requested == ENGINE_CPSAT and out.fallback is True
    assert out.disclosures and "现行引擎" in out.disclosures[0]["zh"]
    assert out.telemetry is not None
    assert "P1-F" in (out.telemetry.get("fallback_reason") or "")
    assert out.telemetry["status"] == "ERROR"


def test_cpsat_fail_loud_raises_not_ready():
    with pytest.raises(ServingNotReady):
        solve_trip(_mini_snapshot(), flag=ENGINE_CPSAT, fail_loud=True)


def test_cpsat_serves_when_ready_on_real_fixture():
    out = solve_trip(_g02_snapshot(), flag=ENGINE_CPSAT, _ready=lambda: (True, ""))
    assert out.engine == ENGINE_CPSAT and out.fallback is False
    assert out.solution is not None and out.solution.status == "OPTIMAL"
    assert out.telemetry is not None
    assert len(out.telemetry["snapshot_hash"]) == 64
    assert out.telemetry["unplaced_count"] == 0


def test_cpsat_exception_falls_back_in_production(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(entry, "solve_snapshot", _boom)
    monkeypatch.setattr(entry, "serving_ready", lambda: (True, ""))
    out = solve_trip(_mini_snapshot(), flag=ENGINE_CPSAT)
    assert out.engine == ENGINE_LEGACY and out.fallback is True
    assert out.disclosures and out.telemetry["error"]
    with pytest.raises(RuntimeError):
        solve_trip(
            _mini_snapshot(),
            flag=ENGINE_CPSAT,
            fail_loud=True,
            _ready=lambda: (True, ""),
        )


# --- shadow: cascade serves, model double-solves for telemetry (M6) -----------


def test_shadow_sampling_gate_is_deterministic_and_partitioned():
    in_key = next(k for k in (str(i) for i in range(100)) if should_sample(k))
    out_key = next(k for k in (str(i) for i in range(100)) if not should_sample(k))
    assert should_sample(in_key) is True and should_sample(in_key) is True
    assert should_sample(out_key) is False


def test_shadow_sampled_out_is_plain_legacy(monkeypatch):
    def _boom(*a, **kw):  # pragma: no cover
        raise AssertionError("sampled-out shadow must not solve")

    monkeypatch.setattr(entry, "solve_snapshot", _boom)
    out_key = next(k for k in (str(i) for i in range(100)) if not should_sample(k))
    out = solve_trip(_mini_snapshot(), flag=ENGINE_SHADOW, sample_key=out_key)
    assert out.engine == ENGINE_LEGACY and out.solution is None
    assert out.fallback is False and out.telemetry is None


def test_shadow_sampled_in_records_model_telemetry():
    in_key = next(k for k in (str(i) for i in range(100)) if should_sample(k))
    out = solve_trip(_mini_snapshot(), flag=ENGINE_SHADOW, sample_key=in_key)
    assert out.engine == ENGINE_LEGACY  # the cascade still serves
    assert out.solution is not None and out.solution.status == "OPTIMAL"
    assert out.telemetry is not None and out.telemetry["engine"] == ENGINE_SHADOW


# --- M8 rollback: flip the flag back ------------------------------------------


def test_rollback_flip_env_back_to_legacy(monkeypatch):
    calls = {"n": 0}
    real = entry.solve_snapshot

    def _counted(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(entry, "solve_snapshot", _counted)
    monkeypatch.setenv(ENV_FLAG, ENGINE_CPSAT)
    during = solve_trip(_mini_snapshot())
    assert during.fallback is True  # not ready → cascade serves
    assert calls["n"] == 0  # not-ready short-circuits BEFORE any solve

    monkeypatch.setenv(ENV_FLAG, ENGINE_LEGACY)
    after = solve_trip(_mini_snapshot())
    assert after.engine == ENGINE_LEGACY and after.fallback is False
    assert calls["n"] == 0


# --- F-36 telemetry shape ------------------------------------------------------


def test_telemetry_record_shape_with_honest_blanks():
    snapshot = _mini_snapshot()
    solution = Solution(
        status="OPTIMAL",
        items=[SolutionItem(cid="c1", day=1, start_min=510, end_min=600)],
        unplaced=[],
        wall_ms=7,
    )
    record = solve_telemetry(snapshot, solution, engine=ENGINE_CPSAT)
    for key in (
        "snapshot_hash",
        "schema_version",
        "engine",
        "status",
        "wall_ms",
        "unplaced_count",
        "fill_count",
        "hint_used",
        "slack_level",
        "n_vars",
        "n_cons",
        "solver_version",
        "fallback_reason",
        "emitted_at",
    ):
        assert key in record, key
    assert record["fill_count"] == 0  # c1 is requested, not fill
    assert record["slack_level"] is None and record["n_vars"] is None
    assert isinstance(record["solver_version"], str) and record["solver_version"]
