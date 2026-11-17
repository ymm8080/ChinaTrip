"""F-14 access intervals: shuttle profiles → outbound/return interval math.
The SAME functions feed the model constraints (C-08) and card assembly
(F-30), so card times ≡ leg times by construction.
"""

from __future__ import annotations


def hhmm_to_min(text: str) -> int:
    hh, mm = text.split(":")
    return int(hh) * 60 + int(mm)


def min_to_hhmm(minutes: int) -> str:
    minutes = max(0, min(minutes, 24 * 60))
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def choose_departure(profile, earliest_min: int) -> str | None:
    """First shuttle departure at/after earliest_min; None if none fits."""
    for dep in profile.departures:
        if hhmm_to_min(dep) >= earliest_min:
            return dep
    return None


def outbound_interval(profile, depart_hhmm: str) -> dict:
    """Origin → gateway (taxi) → board → ride → last mile → POI arrival."""
    depart = hhmm_to_min(depart_hhmm)
    board = depart + profile.taxi_minutes
    arrive_poi = board + profile.ride_minutes + profile.last_mile_minutes
    return {
        "gateway": profile.gateway,
        "depart": depart,
        "board": board,
        "arrive_poi": arrive_poi,
        "ride_minutes": profile.ride_minutes,
        "last_mile_minutes": profile.last_mile_minutes,
        "taxi_minutes": profile.taxi_minutes,
    }


def return_interval(profile, visit_end_min: int, min_buffer: int = 8) -> dict | None:
    """First return departure at/after visit end + buffer → city arrival."""
    earliest = visit_end_min + min_buffer
    for ret in profile.returns:
        dep = hhmm_to_min(ret)
        if dep >= earliest:
            arrive = dep + profile.ride_minutes + profile.last_mile_minutes
            return {"return_depart": dep, "arrive_city": arrive}
    return None


def total_one_way_minutes(profile) -> int:
    return (
        profile.taxi_minutes
        + profile.wait_minutes
        + profile.ride_minutes
        + profile.last_mile_minutes
    )
