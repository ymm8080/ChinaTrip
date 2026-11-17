"""F-11 travel matrix: measured legs first, haversine estimate fallback,
with a 100%-coverage report inside the selected candidate set."""

from __future__ import annotations

from typing import Optional

DEFAULT_TRAVEL_MINUTES = 45
HAVERSINE_MIN_PER_KM = 2.6
HAVERSINE_FLOOR_MINUTES = 5


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    import math as _m

    rlon1, rlat1, rlon2, rlat2 = map(_m.radians, (lon1, lat1, lon2, lat2))
    dlon, dlat = rlon2 - rlon1, rlat2 - rlat1
    h = _m.sin(dlat / 2) ** 2 + _m.cos(rlat1) * _m.cos(rlat2) * _m.sin(dlon / 2) ** 2
    return 2 * 6371.0 * _m.asin(_m.sqrt(h))


def estimate_minutes(lon1: float, lat1: float, lon2: float, lat2: float) -> int:
    km = haversine_km(lon1, lat1, lon2, lat2)
    return max(HAVERSINE_FLOOR_MINUTES, int(round(km * HAVERSINE_MIN_PER_KM)) + 3)


def build_matrix(
    candidates,
    measured_legs,
) -> tuple[dict[tuple[str, str], int], dict]:
    """candidates: iterable of objects with key/lon/lat; measured_legs:
    iterable of objects with from_key/to_key/minutes/mode.

    Returns (matrix, coverage) where matrix maps (from_key, to_key) → minutes
    and coverage reports measured/estimated/uncovered pair counts.
    """
    by_key: dict[str, object] = {}
    for cand in candidates:
        by_key[getattr(cand, "key", None) or getattr(cand, "cid")] = cand

    matrix: dict[tuple[str, str], int] = {}
    for leg in measured_legs:
        matrix[(leg.from_key, leg.to_key)] = int(leg.minutes)

    keys = list(by_key.keys())
    points = {
        k: (getattr(by_key[k], "lon", None), getattr(by_key[k], "lat", None))
        for k in keys
    }
    uncovered: list[tuple[str, str]] = []
    estimated = 0
    measured_pairs = {
        (leg.from_key, leg.to_key)
        for leg in measured_legs
        if (leg.from_key, leg.to_key) in matrix
    }
    covered = 0
    total = 0
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            for src, dst in ((a, b), (b, a)):
                total += 1
                if (src, dst) in matrix:
                    covered += 1
                    continue
                lon1, lat1 = points[src]
                lon2, lat2 = points[dst]
                if None in (lon1, lat1, lon2, lat2):
                    uncovered.append((src, dst))
                    continue
                matrix[(src, dst)] = estimate_minutes(lon1, lat1, lon2, lat2)
                estimated += 1
                covered += 1

    coverage = {
        "pairs": total,
        "measured": sum(
            1
            for p in [
                (a, b)
                for i, a in enumerate(keys)
                for b in keys[i + 1 :]
                for a2, b2 in ((a, b), (b, a))
            ]
            if p in measured_pairs
        ),
        "estimated": estimated,
        "uncovered": uncovered,
        "coverage_pct": round(100.0 * covered / max(1, total), 1),
    }
    return matrix, coverage


def lookup(
    matrix: dict[tuple[str, str], int], src: Optional[str], dst: Optional[str]
) -> int:
    """Matrix lookup with the legacy default (solver._travel_cost 口径)."""
    if src is None or dst is None:
        return DEFAULT_TRAVEL_MINUTES
    return matrix.get((src, dst), DEFAULT_TRAVEL_MINUTES)
