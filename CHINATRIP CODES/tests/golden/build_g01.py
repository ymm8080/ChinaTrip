# -*- coding: utf-8 -*-
"""Build the anonymized G-01 golden fixture from the real incident payload.

Source: workspace dump `session_target.json` (session 24379abd, Beijing 2 days
starting 2026-11-25, five must-visits). All identifiers are stripped — the
committed fixture must contain no device id, account id, session id or email.

Usage:  python tests/golden/build_g01.py <path-to-session_target.json>
Writes: tests/golden/g01.json
"""

from __future__ import annotations

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "g01.json")

EXPECT = [
    {
        "type": "requested_coverage",
        "args": {
            "note": "requested timed OR unplaced+disclosure; untimed = failure (B-01)"
        },
    },
    {
        "type": "sequence",
        "args": {
            "day": 1,
            "order": ["天安门广场", "慕田峪长城"],
            "note": "E-1: direct departure after Tiananmen",
        },
    },
    {
        "type": "no_unrequested_before",
        "args": {
            "day": 1,
            "before": "慕田峪长城",
            "note": "E-1/C-15: no filler may precede the remote leg",
        },
    },
    {
        "type": "time_range",
        "args": {"day": 1, "name": "天安门广场", "start": "07:00", "end": "08:45"},
    },
    {
        "type": "same_venue",
        "args": {
            "day": 1,
            "meal": "lunch",
            "name": "慕田峪长城",
            "note": "E-1/C-10: lunch at the remote site, not in the city",
        },
    },
    {
        "type": "card_leg_consistent",
        "args": {
            "day": 1,
            "name": "慕田峪长城",
            "note": "B-03c: visit.start == leg.arrive + last_mile",
        },
    },
    {
        "type": "time_range",
        "args": {
            "day": 1,
            "name": "慕田峪长城",
            "start": "10:50",
            "end": "11:25",
            "note": "shuttle 09:30 + 90min ride + 8min last mile ≈ 11:08",
        },
    },
    {
        "type": "no_entry_cap_breach",
        "args": {"caps": {"generic": "16:30", "big": "15:30"}},
    },
    {"type": "deterministic", "args": {"runs": 2}},
]


def _key(item: dict) -> str:
    return str(item.get("poi_id") or item.get("name"))


def build(payload_path: str) -> dict:
    with open(payload_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    plan = payload.get("plan") or {}
    days = plan.get("days") or []
    must_names = list(payload.get("must_visits") or [])
    wish = payload.get("wish_bindings") or {}

    request = {
        "days": int(payload.get("days") or len(days) or 1),
        "cities": list(payload.get("cities") or []),
        "start_date": payload.get("start_date"),
        "musts": [],
        "wishes": [],
        "avoid": list(payload.get("avoid_sites") or []),
        "arrival_time": None,
        "departure_time": None,
        "day1_start": payload.get("comment_day_start"),
        "lang": payload.get("lang", "zh"),
    }

    rid_by_name: dict[str, str] = {}
    for idx, name in enumerate(must_names):
        rid = "r%d" % (idx + 1)
        rid_by_name[name] = rid
        row = wish.get(name) or {}
        loc = row.get("location") or {}
        request["musts"].append(
            {
                "rid": rid,
                "name": name,
                "poi_id": row.get("source_poi_id"),
                "importance": len(must_names) - idx,
                "duration_tier": None,
                "day_hint": None,
                "lon": loc.get("lon"),
                "lat": loc.get("lat"),
            }
        )

    candidates = []
    seen: set[str] = set()
    seen_names: set[str] = set()
    access_profiles = []
    travel = []

    def add_candidate(item: dict) -> None:
        name = str(item.get("name") or "")
        key = _key(item)
        if key in seen or not name:
            return
        seen.add(key)
        seen_names.add(name)
        loc = item.get("location") or {}
        is_must = name in rid_by_name
        candidates.append(
            {
                "cid": "c%d" % (len(candidates) + 1),
                "name": name,
                "poi_id": item.get("poi_id"),
                "kind": "requested" if is_must else "fill",
                "rid": rid_by_name.get(name),
                "category": item.get("category"),
                "tier": item.get("tier"),
                "lon": loc.get("lon"),
                "lat": loc.get("lat"),
                "opening_hours": item.get("opening_hours"),
                "best_visit_time": item.get("best_visit_time"),
                "indoor": item.get("indoor"),
                "rain_ok": item.get("rain_ok"),
                "suggested_duration_min": item.get("duration_minutes"),
                "remote": bool(item.get("remote")) or name.startswith("慕田峪"),
                "city": (payload.get("cities") or [None])[0],
            }
        )

    for day in days:
        items = [
            it
            for it in day.get("items", ())
            if it.get("category") not in ("food", "hotel")
        ]
        for pos, item in enumerate(items):
            add_candidate(item)
            nxt = items[pos + 1] if pos + 1 < len(items) else None
            if nxt and item.get("next_leg_minutes"):
                travel.append(
                    {
                        "from_key": _key(item),
                        "to_key": _key(nxt),
                        "minutes": int(item["next_leg_minutes"]),
                        "mode": item.get("next_leg_mode") or "taxi",
                        "source": item.get("leg_source") or "estimate",
                    }
                )
            elif nxt and _has_xy(item) and _has_xy(nxt):
                km = _haversine_km(item["location"], nxt["location"])
                travel.append(
                    {
                        "from_key": _key(item),
                        "to_key": _key(nxt),
                        "minutes": max(5, int(round(km * 2.6)) + 3),
                        "mode": "taxi",
                        "source": "haversine",
                    }
                )
            if name_is_remote(item) and item.get("access_ride_minutes"):
                access_profiles.append(
                    {
                        "gateway": item.get("access_boarding_stop") or "",
                        "to_poi": _key(item),
                        "ride_minutes": int(item["access_ride_minutes"]),
                        "wait_minutes": int(item.get("access_wait_minutes") or 0),
                        "last_mile_minutes": int(
                            item.get("access_last_mile_minutes") or 0
                        ),
                        "departures": [
                            str(t) for t in (item.get("access_depart_times") or ())
                        ],
                        "returns": [
                            str(t) for t in (item.get("access_return_times") or ())
                        ],
                        "taxi_minutes": int(
                            (item.get("next_leg_detail") or {}).get("taxi_minutes") or 0
                        ),
                        "fare_text": item.get("access_fare_text"),
                        "operator": item.get("access_operator"),
                    }
                )

    # any must missing from the plan still needs a requested candidate
    for name, rid in rid_by_name.items():
        if name in seen_names:
            continue
        row = wish.get(name) or {}
        loc = row.get("location") or {}
        candidates.append(
            {
                "cid": "c%d" % (len(candidates) + 1),
                "name": name,
                "poi_id": row.get("source_poi_id"),
                "kind": "requested",
                "rid": rid,
                "category": row.get("category"),
                "tier": None,
                "lon": loc.get("lon"),
                "lat": loc.get("lat"),
                "opening_hours": row.get("opening_hours"),
                "best_visit_time": row.get("best_visit_time"),
                "indoor": row.get("indoor"),
                "rain_ok": row.get("rain_ok"),
                "suggested_duration_min": row.get("suggested_duration_min"),
                "remote": name.startswith("慕田峪"),
                "city": (payload.get("cities") or [None])[0],
            }
        )

    # derive a travel arc for every access profile (gateway -> remote POI)
    for prof in access_profiles:
        travel.append(
            {
                "from_key": prof["gateway"],
                "to_key": prof["to_poi"],
                "minutes": prof["taxi_minutes"]
                + prof["wait_minutes"]
                + prof["ride_minutes"]
                + prof["last_mile_minutes"],
                "mode": "access",
                "source": "access-profile",
            }
        )

    fixture = {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": request,
        "candidates": candidates,
        "access_profiles": access_profiles,
        "travel": travel,
        "expect": EXPECT,
        "provenance": {
            "incident": "Beijing 2 days 2026-11-25, five musts (ids stripped)",
            "built_at": "2026-11-17",
            "builder": "tests/golden/build_g01.py",
            "note": "E-1..E-4 from cpsat_as_is §5; audit M7 schema",
        },
    }
    return fixture


def _has_xy(item: dict) -> bool:
    loc = item.get("location") or {}
    return loc.get("lon") is not None and loc.get("lat") is not None


def _haversine_km(a: dict, b: dict) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a["lon"], a["lat"], b["lon"], b["lat"]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def name_is_remote(item: dict) -> bool:
    return bool(item.get("remote")) or str(item.get("name") or "").startswith("慕田峪")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    fixture = build(argv[1])
    blob = json.dumps(fixture, ensure_ascii=False, indent=1)
    banned = [
        "dev-hs4e9vhk",
        "914542970",
        "@qq.com",
        "24379abd",
        "session_id",
        "device_id",
        "account_id",
    ]
    leaked = [b for b in banned if b in blob]
    if leaked:
        print("ANONYMIZATION FAILED:", leaked)
        return 1
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(blob + "\n")
    print("wrote", OUT)
    print(
        "musts=%d candidates=%d access=%d travel=%d expect=%d"
        % (
            len(fixture["request"]["musts"]),
            len(fixture["candidates"]),
            len(fixture["access_profiles"]),
            len(fixture["travel"]),
            len(fixture["expect"]),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
