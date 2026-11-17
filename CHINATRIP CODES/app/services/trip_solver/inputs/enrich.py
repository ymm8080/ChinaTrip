"""F-03 enrichment + M14 readiness report.

EnrichedSnapshot = base FactSnapshot + per-candidate derived inputs:
entry caps (F-12), duration tiers (F-15), travel matrix (F-11), weather
conditions (F-13), access intervals (F-14). Pure — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from .duration import duration_tier
from .hours_caps import entry_cap_minutes, parse_first_window
from .travel import build_matrix
from .weather import weather_conditions


@dataclass
class EnrichedSnapshot:
    snapshot: object
    caps: dict[str, tuple[int | None, str]]
    windows: dict[str, tuple[int, int] | None]
    tiers: dict[str, tuple[int, int, int, bool]]
    matrix: dict[tuple[str, str], int]
    matrix_coverage: dict
    weather: dict[tuple[str, str], dict]
    access_by_poi: dict[str, object]
    readiness: dict

    def cap(self, cid: str) -> int | None:
        return self.caps.get(cid, (None, "unknown"))[0]


def enrich(
    snapshot, weather_days: tuple[tuple[str, str, str], ...] = ()
) -> EnrichedSnapshot:
    from .access import total_one_way_minutes as _tw  # noqa: F401 (re-exported)

    caps: dict[str, tuple[int | None, str]] = {}
    windows: dict[str, tuple[int, int] | None] = {}
    tiers: dict[str, tuple[int, int, int, bool]] = {}
    keys: list[str] = []

    for cand in snapshot.candidates:
        key = cand.poi_id or cand.cid
        keys.append(key)
        window = parse_first_window(cand.opening_hours)
        windows[cand.cid] = window
        cap, reason = entry_cap_minutes(
            name=cand.name,
            category=cand.category,
            best_visit_time=cand.best_visit_time,
            opening_hours_text=cand.opening_hours,
            duration_min=cand.suggested_duration_min,
            tier=cand.tier,
        )
        caps[cand.cid] = (cap, reason)
        tiers[cand.cid] = duration_tier(cand.suggested_duration_min, cand.category)

    class _Keyed:
        """Read-only view exposing .key/.lon/.lat for the matrix builder."""

        def __init__(self, cand, key):
            self.cid = cand.cid
            self.key = key
            self.lon = cand.lon
            self.lat = cand.lat

    keyed = []
    key_by_cid = {}
    for cand, key in zip(snapshot.candidates, keys):
        keyed.append(_Keyed(cand, key))
        key_by_cid[cand.cid] = key

    class _Leg:
        def __init__(self, leg):
            self.from_key = leg.from_key
            self.to_key = leg.to_key
            self.minutes = leg.minutes
            self.mode = leg.mode

    matrix, coverage = build_matrix(keyed, [_Leg(t) for t in snapshot.travel])

    access_by_poi: dict[str, object] = {}
    for prof in snapshot.access_profiles:
        access_by_poi[prof.to_poi] = prof

    weather_all = tuple(weather_days) or snapshot.weather
    weather = weather_conditions(weather_all, snapshot.candidates)

    readiness = readiness_report(
        snapshot=snapshot,
        windows=windows,
        access_by_poi=access_by_poi,
        tiers=tiers,
        coverage=coverage,
    )

    return EnrichedSnapshot(
        snapshot=snapshot,
        caps=caps,
        windows=windows,
        tiers=tiers,
        matrix=matrix,
        matrix_coverage=coverage,
        weather=weather,
        access_by_poi=access_by_poi,
        readiness=readiness,
    )


def readiness_report(*, snapshot, windows, access_by_poi, tiers, coverage) -> dict:
    """M14 data-readiness gates. Values are computed honestly; a gate can
    fail on a sparse fixture (G-01 is known-sparse for indoor/rain_ok)."""
    total = len(snapshot.candidates)
    hours_ok = sum(1 for w in windows.values() if w is not None)
    remote_no_access = [
        c.cid
        for c in snapshot.candidates
        if getattr(c, "remote", False) and (c.poi_id or c.cid) not in access_by_poi
    ]
    indoor_ok = sum(
        1 for c in snapshot.candidates if c.indoor is not None or c.rain_ok is not None
    )
    tier_ok = sum(1 for t in tiers.values() if t is not None)

    gates = {
        "hours_parse": {
            "value": round(hours_ok / max(1, total), 3),
            "threshold": 0.99,
            "pass": total > 0 and hours_ok == total or hours_ok / max(1, total) >= 0.99,
        },
        "remote_access_coverage": {
            "value": f"{len(remote_no_access)} missing",
            "threshold": "0 missing",
            "pass": not remote_no_access,
            "missing": remote_no_access,
        },
        "indoor_rain_ok": {
            "value": round(indoor_ok / max(1, total), 3),
            "threshold": 0.95,
            "pass": total > 0 and indoor_ok / max(1, total) >= 0.95,
        },
        "duration_tier": {
            "value": round(tier_ok / max(1, total), 3),
            "threshold": 1.0,
            "pass": tier_ok == total,
        },
        "matrix_coverage": {
            "value": coverage.get("coverage_pct"),
            "threshold": 100.0,
            "pass": not coverage.get("uncovered"),
        },
    }
    return {
        "gates": gates,
        "all_pass": all(g["pass"] for g in gates.values()),
        "note": "G-01 fixture is known-sparse on indoor/rain_ok (backfill is "
        "a data task, audit M5/M14); sparse fixtures are accepted for "
        "skeleton tests, real-store snapshots must pass all gates.",
    }
