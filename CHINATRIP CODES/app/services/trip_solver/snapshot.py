"""Snapshot loading + hashing (F-03, P1-A).

A snapshot is a static JSON fixture in P1-A. Later packages build the same
FactSnapshot from the live stores; the solver never reads a DB directly.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .types import (
    SNAPSHOT_SCHEMA_VERSION,
    AccessProfile,
    CandidateItem,
    FactSnapshot,
    FixedPin,
    RequestedItem,
    TravelLeg,
    TripRequest,
)


def _req(raw: dict[str, Any], kind: str) -> RequestedItem:
    tier = raw.get("duration_tier")
    return RequestedItem(
        rid=str(raw["rid"]),
        name=str(raw["name"]),
        poi_id=raw.get("poi_id"),
        kind=kind,
        importance=int(raw.get("importance", 3)),
        duration_tier=tuple(tier) if tier else None,
        day_hint=raw.get("day_hint"),
    )


def _cand(raw: dict[str, Any]) -> CandidateItem:
    return CandidateItem(
        cid=str(raw["cid"]),
        name=str(raw["name"]),
        poi_id=raw.get("poi_id"),
        kind=raw.get("kind", "fill"),
        rid=raw.get("rid"),
        category=raw.get("category"),
        tier=raw.get("tier"),
        quality=raw.get("quality"),
        lon=raw.get("lon"),
        lat=raw.get("lat"),
        opening_hours=raw.get("opening_hours"),
        best_visit_time=raw.get("best_visit_time"),
        indoor=raw.get("indoor"),
        rain_ok=raw.get("rain_ok"),
        suggested_duration_min=raw.get("suggested_duration_min"),
        remote=bool(raw.get("remote", False)),
        city=raw.get("city"),
    )


def _access(raw: dict[str, Any]) -> AccessProfile:
    return AccessProfile(
        gateway=str(raw["gateway"]),
        to_poi=str(raw["to_poi"]),
        ride_minutes=int(raw["ride_minutes"]),
        wait_minutes=int(raw.get("wait_minutes", 0)),
        last_mile_minutes=int(raw.get("last_mile_minutes", 0)),
        departures=tuple(raw.get("departures", ())),
        returns=tuple(raw.get("returns", ())),
        taxi_minutes=int(raw.get("taxi_minutes", 0)),
        fare_text=raw.get("fare_text"),
        operator=raw.get("operator"),
    )


def _leg(raw: dict[str, Any]) -> TravelLeg:
    return TravelLeg(
        from_key=str(raw["from_key"]),
        to_key=str(raw["to_key"]),
        minutes=int(raw["minutes"]),
        mode=raw.get("mode", "taxi"),
        source=raw.get("source", "estimate"),
    )


def snapshot_from_dict(raw: dict[str, Any]) -> FactSnapshot:
    req_raw = raw["request"]
    request = TripRequest(
        days=int(req_raw["days"]),
        cities=tuple(req_raw.get("cities", ())),
        start_date=req_raw.get("start_date"),
        musts=tuple(_req(r, "must") for r in req_raw.get("musts", ())),
        wishes=tuple(_req(r, "wish") for r in req_raw.get("wishes", ())),
        avoid=tuple(req_raw.get("avoid", ())),
        arrival_time=req_raw.get("arrival_time"),
        departure_time=req_raw.get("departure_time"),
        day1_start=req_raw.get("day1_start"),
        lang=req_raw.get("lang", "zh"),
        pins=tuple(
            FixedPin(
                rid=str(p["rid"]),
                day=int(p["day"]),
                start_min=int(p["start_min"]),
                cid=str(p.get("cid", "")),
            )
            for p in req_raw.get("pins", ())
        ),
    )
    return FactSnapshot(
        schema_version=int(raw.get("schema_version", SNAPSHOT_SCHEMA_VERSION)),
        request=request,
        candidates=tuple(_cand(c) for c in raw.get("candidates", ())),
        access_profiles=tuple(_access(a) for a in raw.get("access_profiles", ())),
        travel=tuple(_leg(t) for t in raw.get("travel", ())),
        weather=tuple(tuple(w) for w in raw.get("weather", ())),
        library_version=raw.get("library_version", "fixture"),
        source=raw.get("source", "fixture"),
    )


def load_golden(path: str) -> tuple[FactSnapshot, list[dict[str, Any]], dict[str, Any]]:
    """Load a golden scenario -> (snapshot, assertions, provenance)."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    snapshot = snapshot_from_dict(raw)
    expect = list(raw.get("expect", ()))
    provenance = dict(raw.get("provenance", {}))
    return snapshot, expect, provenance


def load_snapshot(path: str) -> FactSnapshot:
    return load_golden(path)[0]


def snapshot_hash(snapshot: FactSnapshot) -> str:
    """Stable content hash — telemetry + determinism guard key."""
    payload = {
        "schema_version": snapshot.schema_version,
        "request": {
            "days": snapshot.request.days,
            "cities": list(snapshot.request.cities),
            "start_date": snapshot.request.start_date,
            "musts": [
                (r.rid, r.name, r.poi_id, r.importance) for r in snapshot.request.musts
            ],
            "wishes": [(r.rid, r.name, r.poi_id) for r in snapshot.request.wishes],
            "avoid": list(snapshot.request.avoid),
            "arrival_time": snapshot.request.arrival_time,
            "departure_time": snapshot.request.departure_time,
            "day1_start": snapshot.request.day1_start,
        },
        "candidates": [
            (
                c.cid,
                c.name,
                c.poi_id,
                c.kind,
                c.rid,
                c.category,
                c.lon,
                c.lat,
                c.opening_hours,
                c.suggested_duration_min,
                c.remote,
            )
            for c in snapshot.candidates
        ],
        "access_profiles": [
            (
                a.gateway,
                a.to_poi,
                a.ride_minutes,
                a.wait_minutes,
                a.last_mile_minutes,
                list(a.departures),
                list(a.returns),
                a.taxi_minutes,
            )
            for a in snapshot.access_profiles
        ],
        "travel": [
            (t.from_key, t.to_key, t.minutes, t.mode, t.source) for t in snapshot.travel
        ],
        "weather": [list(w) for w in snapshot.weather],
        "library_version": snapshot.library_version,
    }
    blob = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def default_golden_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    code_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    return os.path.join(code_root, "tests", "golden", "g01.json")
