"""Core data types for the trip-level solver (P1-A skeleton).

Kept dependency-free so every later package (model core, assembly, shadow)
can import it without pulling in OR-Tools or the legacy agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

SNAPSHOT_SCHEMA_VERSION = 1

RequestedKind = Literal["must", "wish"]
CandidateKind = Literal["requested", "fill"]


@dataclass(frozen=True)
class RequestedItem:
    """A user-requested item (must or wish). Carries the importance weight."""

    rid: str
    name: str
    poi_id: Optional[str] = None
    kind: RequestedKind = "must"
    importance: int = 3
    duration_tier: Optional[tuple[int, int, int]] = None  # (min, typ, max)
    day_hint: Optional[int] = None


@dataclass(frozen=True)
class CandidateItem:
    """A schedulable candidate. `kind=fill` items can never outrank requested ones."""

    cid: str
    name: str
    poi_id: Optional[str] = None
    kind: CandidateKind = "fill"
    rid: Optional[str] = None
    category: Optional[str] = None
    tier: Optional[int] = None
    quality: Optional[float] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    opening_hours: Optional[str] = None
    best_visit_time: Optional[str] = None
    indoor: Optional[str] = None
    rain_ok: Optional[str] = None
    suggested_duration_min: Optional[int] = None
    remote: bool = False


@dataclass(frozen=True)
class AccessProfile:
    """Shuttle / access-service interval template (F-14)."""

    gateway: str
    to_poi: str
    ride_minutes: int
    wait_minutes: int = 0
    last_mile_minutes: int = 0
    departures: tuple[str, ...] = ()
    returns: tuple[str, ...] = ()
    taxi_minutes: int = 0
    fare_text: Optional[str] = None
    operator: Optional[str] = None


@dataclass(frozen=True)
class TravelLeg:
    """One measured or estimated arc between two keys (poi_id or name)."""

    from_key: str
    to_key: str
    minutes: int
    mode: str = "taxi"
    source: str = "estimate"


@dataclass(frozen=True)
class FixedPin:
    """C-04: an immovable placement (iron rule 19)."""

    rid: str
    day: int
    start_min: int
    cid: str = ""  # optional direct candidate binding


@dataclass(frozen=True)
class TripRequest:
    days: int
    cities: tuple[str, ...]
    start_date: Optional[str] = None
    musts: tuple[RequestedItem, ...] = ()
    wishes: tuple[RequestedItem, ...] = ()
    avoid: tuple[str, ...] = ()
    arrival_time: Optional[str] = None
    departure_time: Optional[str] = None
    day1_start: Optional[str] = None
    lang: str = "zh"
    pins: tuple["FixedPin", ...] = ()  # C-04 fixed placements


@dataclass(frozen=True)
class FactSnapshot:
    """Immutable solver input (determinism key)."""

    schema_version: int
    request: TripRequest
    candidates: tuple[CandidateItem, ...]
    access_profiles: tuple[AccessProfile, ...] = ()
    travel: tuple[TravelLeg, ...] = ()
    weather: tuple[tuple[str, str, str], ...] = ()  # (poi_id, day_iso, condition)
    library_version: str = "fixture"
    source: str = "fixture"


@dataclass
class SolutionItem:
    """A placed item in the solution (minutes since midnight)."""

    cid: str
    day: int
    start_min: int
    end_min: int
    kind: str = "visit"
    pinned: bool = False
    source: str = "model"


@dataclass
class Solution:
    """Solver output. INFEASIBLE always carries a certificate, never a fallback."""

    status: str  # OPTIMAL | FEASIBLE | INFEASIBLE
    items: list[SolutionItem] = field(default_factory=list)
    unplaced: list[dict] = field(default_factory=list)
    disclosures: list[str] = field(default_factory=list)
    slack_level: int = 0
    certificate: list[str] = field(default_factory=list)
    wall_ms: Optional[int] = None


def validate_snapshot(snapshot: FactSnapshot) -> list[str]:
    """Structural validation; returns a list of human-readable errors (empty = ok)."""
    errors: list[str] = []

    if snapshot.schema_version != SNAPSHOT_SCHEMA_VERSION:
        errors.append(
            "schema_version %r != %r"
            % (snapshot.schema_version, SNAPSHOT_SCHEMA_VERSION)
        )
    if snapshot.request.days < 1:
        errors.append("request.days must be >= 1")
    if not snapshot.request.cities:
        errors.append("request.cities is empty")

    seen_cids: set[str] = set()
    rid_by_poi: dict[str, str] = {}
    for req in snapshot.request.musts + snapshot.request.wishes:
        if req.poi_id:
            rid_by_poi[req.poi_id] = req.rid
    for cand in snapshot.candidates:
        if cand.cid in seen_cids:
            errors.append("duplicate cid %r" % cand.cid)
        seen_cids.add(cand.cid)
        if cand.kind == "requested" and not cand.rid:
            errors.append("requested candidate %r has no rid" % cand.cid)
        if cand.lon is not None and not (-180.0 <= cand.lon <= 180.0):
            errors.append("candidate %r lon out of range" % cand.cid)
        if cand.lat is not None and not (-90.0 <= cand.lat <= 90.0):
            errors.append("candidate %r lat out of range" % cand.cid)

    covered = {c.rid for c in snapshot.candidates if c.kind == "requested" and c.rid}
    for req in snapshot.request.musts:
        if req.rid not in covered:
            errors.append(
                "must %r (%s) has no requested candidate" % (req.rid, req.name)
            )

    for prof in snapshot.access_profiles:
        if prof.ride_minutes <= 0:
            errors.append("access profile %r has non-positive ride time" % prof.gateway)

    return errors
