"""F-61 relative scoring — ONE scorer, both engines (Q5: keep the legacy
plan_score constants numerically, 2026-11-17 accepted).

The legacy scorer (``app.services.itinerary.scoring.plan_score``) works on
``ItineraryPlan`` cards — and both sides can produce one: the replay scores
the cascade's actual plan, the model side materialises the Solution (F-30)
and scores that. Per-scenario Δ ≥ −2% (F-62) is the companion criterion to
not-worse; rain-day sets derive from the snapshot's weather rows with the
same city→day mapping the engines consume.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from ..types import FactSnapshot

HEAVY_MARKS = ("heavy", "大雨", "暴雨")


def rain_day_sets(
    snapshot: "FactSnapshot",
) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    """snapshot.weather rows → (rain_days, heavy_rain_days) keyed by city.

    Mirrors the legacy ``_rain_map`` contract (city → set[day-index]);
    conditions are bilingual-safe ("light rain" / "小雨").
    """
    start = getattr(snapshot.request, "start_date", None)
    if not start or not snapshot.weather:
        return {}, {}
    try:
        base = datetime.date.fromisoformat(str(start))
    except ValueError:
        return {}, {}
    poi_city = {c.poi_id: c.city for c in snapshot.candidates if c.poi_id and c.city}
    default_city = snapshot.request.cities[0] if snapshot.request.cities else ""
    rain: dict[str, set[int]] = {}
    heavy: dict[str, set[int]] = {}
    for row in snapshot.weather:
        poi_id, day_iso, cond = row[0], row[1], (str(row[2]) if len(row) > 2 else "")
        if not cond:
            continue
        text = cond
        if ("rain" not in text.lower()) and ("雨" not in text):
            continue
        try:
            day = (datetime.date.fromisoformat(str(day_iso)) - base).days + 1
        except ValueError:
            continue
        if day < 1 or day > snapshot.request.days:
            continue
        city = poi_city.get(poi_id) or default_city
        rain.setdefault(city, set()).add(day)
        if any(mark in text for mark in HEAVY_MARKS):
            heavy.setdefault(city, set()).add(day)
    return rain, heavy


def score_plan(plan, snapshot: "FactSnapshot") -> Optional[int]:
    """Legacy scorer over either engine's materialised plan (None on
    failure — the report shows the gap honestly instead of crashing)."""
    if plan is None:
        return None
    try:
        from app.services.itinerary.scoring import plan_score

        rain, heavy = rain_day_sets(snapshot)
        return int(plan_score(plan, rain_days=rain, heavy_rain_days=heavy).total)
    except Exception:  # pragma: no cover - scorer contract drift
        return None


def delta_pct(model: Optional[int], legacy: Optional[int]) -> Optional[float]:
    """(model − legacy) / |legacy| × 100; None when either side unscored."""
    if model is None or legacy is None:
        return None
    if legacy == 0:
        return None  # 0-baseline deltas are noise; treat as unscored
    return round((model - legacy) / abs(legacy) * 100.0, 2)


def within_threshold(
    model: Optional[int], legacy: Optional[int], threshold_pct: float = -2.0
) -> Optional[bool]:
    """F-62: model ≥ legacy + threshold_pct% of |legacy|."""
    if model is None or legacy is None:
        return None
    return (model - legacy) >= (threshold_pct / 100.0) * abs(legacy)
