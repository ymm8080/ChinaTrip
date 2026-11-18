# -*- coding: utf-8 -*-
"""Build corpus v1 scenarios g02…g04 (P2-A, F-60).

Derived from the committed fixtures so every scenario stays regenerable:

- g02_tower_late_gate   (B-07 family): observation tower with post-rollback
  library attributes (best_visit_time=any — the heuristic sunset tag was
  rolled back, e87f40e) and late closing hours; the entry cap (930 big-site)
  must hold. Standalone minimal Shanghai 1-day request.
- g03_third_cluster     (B-08 family): G-01 + the third-cluster POI the
  cascade once filled into the remote day (延庆观景台); C-06/C-15 forbid
  unrequested fill on a remote day. Carries the incident's 天安门 07:10
  flag-schedule pin so the remote day keeps the E-1 shape.
- g04_endpoint_transit  (B-11 family): G-01 WITH arrival/departure times →
  C-05 endpoint windows (arrival + 150 floor, departure − 90 buffer); no
  transport info = full day is the G-01 baseline this contrasts against.

Usage:  python tests/golden/build_corpus_v1.py
Writes: tests/golden/g02_tower_late_gate.json, g03_third_cluster.json,
        g04_endpoint_transit.json
"""

from __future__ import annotations

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
G01 = os.path.join(HERE, "g01.json")
BANNED = [
    "dev-hs4e9vhk",
    "914542970",
    "@qq.com",
    "24379abd",
    "session_id",
    "device_id",
    "account_id",
]


def _write(name: str, fixture: dict) -> None:
    blob = json.dumps(fixture, ensure_ascii=False, indent=1)
    leaked = [b for b in BANNED if b in blob]
    if leaked:
        print("ANONYMIZATION FAILED for %s: %s" % (name, leaked))
        raise SystemExit(1)
    out = os.path.join(HERE, name)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(blob + "\n")
    print(
        "wrote %s (candidates=%d expect=%d)"
        % (name, len(fixture["candidates"]), len(fixture["expect"]))
    )


def build_g02() -> dict:
    """B-07: tower must respect the entry cap with post-rollback attributes."""
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": {
            "days": 1,
            "cities": ["上海"],
            "start_date": "2026-11-25",
            "musts": [
                {
                    "rid": "r1",
                    "name": "东方明珠",
                    "importance": 2,
                    "duration_tier": None,
                }
            ],
            "wishes": [],
            "avoid": [],
            "arrival_time": None,
            "departure_time": None,
            "lang": "zh",
        },
        "candidates": [
            {
                "cid": "c1",
                "name": "东方明珠",
                "poi_id": "ct_上海_1",
                "kind": "requested",
                "rid": "r1",
                "category": "sight",
                "tier": 4,
                "lon": 121.4997,
                "lat": 31.2397,
                "opening_hours": "08:30-19:30",
                "best_visit_time": "any",
                "suggested_duration_min": 90,
                "remote": False,
                "city": "上海",
            },
            {
                "cid": "c2",
                "name": "上海中心大厦上海之巅观光厅",
                "poi_id": "ct_上海_2",
                "kind": "fill",
                "category": "sight",
                "tier": 4,
                "lon": 121.5055,
                "lat": 31.2336,
                "opening_hours": "08:30-22:00",
                # post-B-07-fix library state: NO heuristic sunset tag on
                # towers; only real night rows carry evening attributes
                "best_visit_time": "any",
                "suggested_duration_min": 90,
                "remote": False,
                "city": "上海",
            },
        ],
        "access_profiles": [],
        "travel": [],
        "weather": [],
        "expect": [
            {
                "type": "requested_coverage",
                "args": {"note": "B-07 family: must timed or disclosed-unplaced"},
            },
            {
                "type": "no_entry_cap_breach",
                "args": {
                    "caps": {"generic": "16:30", "big": "15:30"},
                    "note": "tower with bvt=any must not start past 15:30/16:30 "
                    "(legacy heuristic scheduled 19:00)",
                },
            },
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": "B-07 tower late-gate: 上海中心大厦 19:00 past cap",
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v1.py",
            "note": "cap semantics unit-checked in tests (caps[c2]=(930, big-site)); "
            "fill placement itself is unrewarded pre-P1-D — the breach check "
            "is non-vacuous on any placed card",
        },
    }


def build_g03(base: dict) -> dict:
    """B-08: third-cluster POI must never land on the remote day."""
    fixture = copy.deepcopy(base)
    fixture["source"] = "golden-fixture-variant"
    fixture["provenance"] = {
        "incident": "B-08 third-cluster: 延庆观景台 filled into the 慕田峪 day",
        "built_at": "2026-11-18",
        "builder": "tests/golden/build_corpus_v1.py",
        "base": "g01.json (ids stripped)",
        "note": "carries the incident's 天安门 07:10 flag-schedule pin so the "
        "remote day keeps the E-1 shape",
    }
    # incident pin: 天安门 07:10 (flag schedule / 升旗)
    fixture["request"]["pins"] = [{"rid": "r1", "day": 1, "start_min": 430}]
    fixture["candidates"].append(
        {
            "cid": "c8",
            "name": "延庆观景台",
            "poi_id": "ct_北京_9",
            "kind": "fill",
            "category": "sight",
            "tier": 12,
            "lon": 116.0570,
            "lat": 40.4580,
            "opening_hours": "08:00-18:00",
            "best_visit_time": "any",
            "suggested_duration_min": 60,
            "remote": False,
            "city": "北京",
        }
    )
    fixture["expect"] = [
        {
            "type": "requested_coverage",
            "args": {"note": "all five musts timed or disclosed-unplaced"},
        },
        {
            "type": "sequence",
            "args": {
                "day": 1,
                "order": ["天安门广场", "慕田峪长城"],
                "note": "E-1 shape with the 07:10 pin",
            },
        },
        {
            "type": "no_unrequested_before",
            "args": {
                "day": 1,
                "before": "慕田峪长城",
                "note": "B-03a/C-15: no filler precedes the remote leg",
            },
        },
        {
            "type": "no_entry_cap_breach",
            "args": {"caps": {"generic": "16:30", "big": "15:30"}},
        },
        {"type": "deterministic", "args": {"runs": 2}},
    ]
    return fixture


def build_g04(base: dict) -> dict:
    """B-11: timed intercity legs → endpoint windows (C-05)."""
    fixture = copy.deepcopy(base)
    fixture["source"] = "golden-fixture-variant"
    fixture["provenance"] = {
        "incident": "B-11 endpoint days: arrival/departure times constrain "
        "day 1 and the last day",
        "built_at": "2026-11-18",
        "builder": "tests/golden/build_corpus_v1.py",
        "base": "g01.json (ids stripped)",
        "note": "arrival 09:00 → day-1 starts ≥ 11:30 (ARRIVAL_FLOOR 150); "
        "departure 19:00 → last day ends ≤ 17:30 (DEPARTURE_BUFFER 90). "
        "No-transport G-01 stays a full-day baseline.",
    }
    fixture["request"]["arrival_time"] = "09:00"
    fixture["request"]["departure_time"] = "19:00"
    fixture["expect"] = [
        {
            "type": "requested_coverage",
            "args": {
                "note": "musts timed or disclosed-unplaced — the endpoint "
                "windows may make all five unseatable, which must be disclosed, "
                "never silently dropped (B-01)"
            },
        },
        {
            "type": "day_start_floor",
            "args": {
                "day": 1,
                "not_before": "11:30",
                "note": "C-05: arrival 09:00 + 150 floor",
            },
        },
        {
            "type": "day_end_ceiling",
            "args": {
                "day": 2,
                "not_after": "17:30",
                "note": "C-05: departure 19:00 − 90 buffer",
            },
        },
        {
            "type": "no_unrequested_before",
            "args": {
                "day": 1,
                "before": "慕田峪长城",
                "note": "C-15 still holds on the endpoint arrival day",
            },
        },
        {"type": "deterministic", "args": {"runs": 2}},
    ]
    return fixture


def main() -> int:
    with open(G01, "r", encoding="utf-8") as fh:
        base = json.load(fh)
    _write("g02_tower_late_gate.json", build_g02())
    _write("g03_third_cluster.json", build_g03(base))
    _write("g04_endpoint_transit.json", build_g04(base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
