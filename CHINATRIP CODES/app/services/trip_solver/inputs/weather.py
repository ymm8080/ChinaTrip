"""F-13 weather conditioning: forecast × indoor/rain_ok → per (cid, day)
penalty level + reason. Weather is input data, never model-internal inference.
"""

from __future__ import annotations

from typing import Optional

RAIN_OUTDOOR_PENALTY = 240  # legacy _MUST_RAIN_OUTDOOR_PENALTY
RAIN_INDOOR_PENALTY = 60  # legacy _MUST_RAIN_INDOOR_PENALTY (kept for musts)


def is_rainy(condition: Optional[str]) -> bool:
    return bool(condition) and "rain" in condition.lower()


def is_heavy_rain(condition: Optional[str]) -> bool:
    return is_rainy(condition) and "heavy" in condition.lower()


def weather_conditions(
    weather: tuple[tuple[str, str, str], ...],
    candidates,
) -> dict[tuple[str, str], dict]:
    """weather: (poi_id, day_iso, condition) rows. Returns
    {(cid, day): {"penalty": int, "forbid": bool, "reason": str|None}}.
    Rainy + outdoor (rain_ok == 'no') → heavy penalty; heavy rain forbids.
    """
    rain_by_poi_day = {(poi_id, day): cond for poi_id, day, cond in weather}
    out: dict[tuple[str, str], dict] = {}
    for cand in candidates:
        poi_id = getattr(cand, "poi_id", None)
        if poi_id is None:
            continue
        for (poi, day), cond in rain_by_poi_day.items():
            if poi != poi_id or not is_rainy(cond):
                continue
            outdoor = (
                getattr(cand, "rain_ok", None) == "no"
                or getattr(cand, "indoor", None) == "no"
            )
            if not outdoor:
                continue
            forbid = is_heavy_rain(cond)
            out[(getattr(cand, "cid"), day)] = {
                "penalty": RAIN_OUTDOOR_PENALTY,
                "forbid": forbid,
                "reason": "rain_outdoor" + ("_heavy" if forbid else ""),
            }
    return out
