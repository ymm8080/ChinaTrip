"""P1-A skeleton tests: G-01 fixture loads, validates, is anonymized, hashes stably.

The end-to-end golden assertions (E-1..E-4) are a skip-marked P1-F target —
they turn green only when the model can actually schedule the trip.
"""

from __future__ import annotations

import json

import pytest

from app.services.trip_solver.snapshot import (
    default_golden_path,
    load_golden,
    snapshot_hash,
)
from app.services.trip_solver.types import validate_snapshot

G01 = default_golden_path()


def test_g01_fixture_exists_and_loads():
    snapshot, expect, provenance = load_golden(G01)
    assert snapshot.schema_version == 2
    assert snapshot.request.days == 2
    assert snapshot.request.cities == ("北京",)
    assert len(expect) >= 9
    assert provenance.get("builder") == "tests/golden/build_g01.py"


def test_g01_validates_clean():
    snapshot = load_golden(G01)[0]
    assert validate_snapshot(snapshot) == []


def test_g01_request_and_candidates():
    snapshot = load_golden(G01)[0]
    names = [r.name for r in snapshot.request.musts]
    assert names == ["天安门广场", "故宫博物院", "慕田峪长城", "天坛", "颐和园"]
    requested = [c for c in snapshot.candidates if c.kind == "requested"]
    assert len(requested) == 5
    assert len({c.name for c in requested}) == 5
    assert all(c.rid for c in requested)
    assert len(snapshot.candidates) >= 7


def test_g01_access_profile_for_mutianyu():
    snapshot = load_golden(G01)[0]
    profiles = [p for p in snapshot.access_profiles if p.to_poi == "ct_北京_8"]
    assert len(profiles) == 1
    prof = profiles[0]
    assert prof.ride_minutes == 90
    assert prof.wait_minutes == 10
    assert prof.last_mile_minutes == 8
    assert "09:30" in prof.departures
    assert "16:30" in prof.returns


def test_g01_travel_legs_present():
    snapshot = load_golden(G01)[0]
    assert len(snapshot.travel) >= 5
    assert any(leg.mode == "access" for leg in snapshot.travel)
    assert any(
        leg.from_key == "ct_北京_13" for leg in snapshot.travel
    )  # 天安门 outbound


def test_snapshot_hash_is_stable():
    h1 = snapshot_hash(load_golden(G01)[0])
    h2 = snapshot_hash(load_golden(G01)[0])
    assert h1 == h2
    assert len(h1) == 64


def test_fixture_is_anonymized():
    with open(G01, "r", encoding="utf-8") as fh:
        raw = fh.read()
    assert "device_id" not in raw
    assert "account_id" not in raw
    assert "session_id" not in raw
    assert "@" not in raw
    assert "dev-hs4e9vhk" not in raw


def test_expect_assertions_use_known_schema_types():
    _, expect, _ = load_golden(G01)
    known = {
        "sequence",
        "time_range",
        "same_venue",
        "card_leg_consistent",
        "no_unrequested_before",
        "requested_coverage",
        "no_entry_cap_breach",
        "disclosure_contains",
        "deterministic",
    }
    assert {a["type"] for a in expect} <= known
    json.dumps(expect)  # must be JSON-serializable for the shadow harness


@pytest.mark.skip(
    reason="P1-F target: G-01 green (E-1..E-4) — model not implemented yet"
)
def test_g01_expected_shapes_red_target():
    # Placeholder documenting the acceptance target; enabled in P1-F.
    assert False
