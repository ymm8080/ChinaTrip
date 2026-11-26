# -*- coding: utf-8 -*-
"""Build corpus v2 scenarios g05…g13 (P2-B, F-60 corpus expansion to ≥ 12).

Families (phases doc P2-B + F-60): rain rebalance, reopen/pins, name
variants (typo proxy), remote-day exclusivity, duration clamp (Q1),
multi-city coherence (C-07), trip-scale convergence (Q3), closed weekday
(C-01), content twins (大足 incident). Every scenario commits the expected
shape BEFORE the model can satisfy it where a later package owns the
semantics (red targets, P1-A precedent) — provenance marks each honestly.

Derived from the committed G-01 fixture where family = a variant of the
incident shape; standalone minimal fixtures otherwise. Regenerable:
`python tests/golden/build_corpus_v2.py` writes byte-identical JSON.

Usage:  python tests/golden/build_corpus_v2.py
Writes: tests/golden/g05_rain_rebalance.json … g13_twin_content_dup.json
"""

from __future__ import annotations

import copy
import datetime
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

# g01 carries one access profile: 前门 ⇄ 慕田峪 (ct_北京_8), 09:30 → 11:08.
MUTIANYU_PROFILE = {
    "gateway": "前门大街北口（北京旅游集散中心发车点）",
    "to_poi": "ct_北京_8",
    "ride_minutes": 90,
    "wait_minutes": 10,
    "last_mile_minutes": 8,
    "departures": ["07:30", "08:30", "09:30", "10:30"],
    "returns": ["14:30", "15:30", "16:30"],
    "taxi_minutes": 0,
    "fare_text": "官网未公布专线车费；运营方咨询 010-83531111",
    "operator": "北京旅游集散中心",
}
# real-ish coordinates (GCJ-02, lon/lat) — same sources the fixtures already use
XY = {
    "天安门广场": (116.4103, 39.9115),
    "故宫博物院": (116.4097, 39.9255),
    "慕田峪长城": (116.5598, 40.4267),
    "天坛": (116.4128, 39.8836),
    "颐和园": (116.2749, 39.9987),
    "王府井大街": (116.4180, 39.9097),
    "景山公园": (116.3971, 39.9254),
    "中国国家博物馆": (116.4039, 39.9050),
    "外滩": (121.4903, 31.2335),
    "豫园": (121.4921, 31.2273),
    "南京路步行街": (121.4756, 31.2334),
    "田子坊": (121.4692, 31.2103),
    "西湖风景名胜区": (120.1494, 30.2459),
    "清河坊": (120.1666, 30.2433),
    "断桥残雪": (120.1502, 30.2589),
    "东方明珠": (121.4997, 31.2397),
    "大足石刻": (105.7181, 29.7065),
}


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


def _must(rid: str, name: str, imp: int, poi_id: str | None = None) -> dict:
    m = {"rid": rid, "name": name, "importance": imp, "duration_tier": None}
    if poi_id:
        m["poi_id"] = poi_id
    return m


def _cand(
    cid: str,
    name: str,
    city: str,
    *,
    kind: str = "fill",
    rid: str | None = None,
    category: str = "sight",
    tier: int = 10,
    lon: float | None = None,
    lat: float | None = None,
    hours: str | None = "08:00-18:00",
    bvt: str = "any",
    dur: int = 90,
    remote: bool = False,
    indoor: str | None = None,
    rain_ok: str | None = None,
    poi_id: str | None = None,
) -> dict:
    xy = XY.get(name)
    c: dict = {
        "cid": cid,
        "name": name,
        "poi_id": poi_id or ("poi_%s" % cid),
        "kind": kind,
        "category": category,
        "tier": tier,
        "lon": lon if lon is not None else (xy[0] if xy else None),
        "lat": lat if lat is not None else (xy[1] if xy else None),
        "opening_hours": hours,
        "best_visit_time": bvt,
        "suggested_duration_min": dur,
        "remote": remote,
        "city": city,
    }
    if rid:
        c["rid"] = rid
    if indoor:
        c["indoor"] = indoor
    if rain_ok:
        c["rain_ok"] = rain_ok
    return c


def _request(days: int, cities: list[str], musts: list[dict], start: str, **kw) -> dict:
    req = {
        "days": days,
        "cities": cities,
        "start_date": start,
        "musts": musts,
        "wishes": [],
        "avoid": [],
        "arrival_time": None,
        "departure_time": None,
        "day1_start": None,
        "lang": "zh",
    }
    req.update(kw)
    return req


def _next_day(iso: str) -> str:
    return (datetime.date.fromisoformat(iso) + datetime.timedelta(days=1)).isoformat()


# --- g05 rain rebalance ------------------------------------------------------


def build_g05(base: dict) -> dict:
    """Rain family: outdoor musts + rain both days; F-13 data lands now,
    the weather penalties/constraints are P1-D (C-11/C-12) — this scenario
    is the committed-before-fix target for them."""
    fixture = copy.deepcopy(base)
    fixture["source"] = "golden-fixture-variant"
    d1 = fixture["request"]["start_date"]
    d2 = _next_day(d1)
    weather: list[list[str]] = []
    by_name = {c["name"]: c for c in fixture["candidates"]}
    outdoor = {"天安门广场", "慕田峪长城", "天坛", "颐和园"}
    for name, cand in by_name.items():
        if name in outdoor:
            cand["rain_ok"] = "no"
            cand["indoor"] = "no"
        elif name in {"梵高星空艺术馆（王府井旗舰店）", "老舍茶馆", "故宫博物院"}:
            cand["rain_ok"] = "yes"
            cand["indoor"] = "yes"
        pid = cand.get("poi_id")
        if pid:
            weather.append([pid, d1, "light rain"])
            weather.append([pid, d2, "heavy rain"])
    fixture["weather"] = weather
    fixture["expect"] = [
        {
            "type": "requested_coverage",
            "args": {"note": "rain family: all musts timed or disclosed-unplaced"},
        },
        {
            "type": "no_entry_cap_breach",
            "args": {"caps": {"generic": "16:30", "big": "15:30"}},
        },
        {"type": "deterministic", "args": {"runs": 2}},
    ]
    fixture["provenance"] = {
        "incident": "rain rebalance family (F-60): outdoor musts under rain both days",
        "built_at": "2026-11-18",
        "builder": "tests/golden/build_corpus_v2.py",
        "base": "g01.json (ids stripped)",
        "note": "F-13 rows + rain_ok/indoor flags land now; the model-side "
        "weather penalty/constraint (C-11/C-12) is P1-D — rain-aware "
        "placement is a red target until then, exactly per the "
        "scenario-before-fix rule.",
    }
    return fixture


# --- g06 reopen/pins ---------------------------------------------------------


def build_g06(base: dict) -> dict:
    """Reopen/pin family (B-09 proxy at snapshot level): two user pins must
    be immovable (C-04 iron rule 19)."""
    fixture = copy.deepcopy(base)
    fixture["source"] = "golden-fixture-variant"
    fixture["request"]["pins"] = [
        {"rid": "r1", "day": 1, "start_min": 430, "cid": "c1"},
        {"rid": "r5", "day": 2, "start_min": 540, "cid": "c7"},
    ]
    fixture["expect"] = [
        {
            "type": "time_range",
            "args": {
                "day": 1,
                "name": "天安门广场",
                "start": "07:00",
                "end": "07:40",
                "requires_pin": "天安门广场",
                "note": "07:10 flag-schedule pin immovable",
            },
        },
        {
            "type": "time_range",
            "args": {
                "day": 2,
                "name": "颐和园",
                "start": "08:30",
                "end": "09:59",
                "requires_pin": "颐和园",
                "note": "user 09:00 pin immovable (reopen-preserve shape)",
            },
        },
        {"type": "requested_coverage", "args": {}},
        {"type": "deterministic", "args": {"runs": 2}},
    ]
    fixture["provenance"] = {
        "incident": "reopen/pin family (B-09 proxy): pins survive any re-solve",
        "built_at": "2026-11-18",
        "builder": "tests/golden/build_corpus_v2.py",
        "base": "g01.json (ids stripped)",
        "note": "C-04 makes pins immovable by construction; the edit-path "
        "re-solve (F-50) lands in P4 — this scenario anchors the pin facts "
        "both consume.",
    }
    return fixture


# --- g07 name variants -------------------------------------------------------


def build_g07(base: dict) -> dict:
    """Typo/alias family (B-10 pool-level proxy): a short-name variant row
    (慕田峪) coexists with the real remote site (慕田峪长城)."""
    fixture = copy.deepcopy(base)
    fixture["source"] = "golden-fixture-variant"
    mutianyu = next(c for c in fixture["candidates"] if c["name"] == "慕田峪长城")
    fixture["candidates"].append(
        {
            "cid": "c9",
            "name": "慕田峪",
            "poi_id": "ct_北京_99",
            "kind": "fill",
            "category": "historic",
            "tier": 9,
            "lon": mutianyu["lon"],
            "lat": mutianyu["lat"],
            "opening_hours": "08:00-17:00",
            "best_visit_time": "any",
            "suggested_duration_min": 180,
            "remote": True,
            "city": "北京",
        }
    )
    fixture["expect"] = [
        {"type": "requested_coverage", "args": {}},
        {
            "type": "no_entry_cap_breach",
            "args": {"caps": {"generic": "16:30", "big": "15:30"}},
        },
        {"type": "deterministic", "args": {"runs": 2}},
    ]
    fixture["provenance"] = {
        "incident": "typo/alias family (B-10 proxy): 慕田峪 variant row vs 慕田峪长城",
        "built_at": "2026-11-18",
        "builder": "tests/golden/build_corpus_v2.py",
        "base": "g01.json (ids stripped)",
        "note": "intent-layer fuzzy binding is F-01/F-02 (outside the model); "
        "the pool-level shape (variant row present) is what this scenario "
        "pins. Whether engines double-book the twin shows in the diff.",
    }
    return fixture


# --- g08 remote-day exclusivity ---------------------------------------------


def build_g08() -> dict:
    """Remote-day family (C-06/C-15): remote must + city must + city fills;
    the remote day may not carry unrequested fill (g03 is the third-cluster
    variant; this is the minimal standalone)."""
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": _request(
            2,
            ["北京"],
            [
                _must("r1", "慕田峪长城", 5, "ct_北京_8"),
                _must("r2", "故宫博物院", 4, "m1_885978e4c8a2"),
            ],
            "2026-11-25",
        ),
        "candidates": [
            _cand(
                "c1",
                "慕田峪长城",
                "北京",
                kind="requested",
                rid="r1",
                category="historic",
                tier=1,
                hours="08:00-17:30",
                dur=180,
                remote=True,
                poi_id="ct_北京_8",
            ),
            _cand(
                "c2",
                "故宫博物院",
                "北京",
                kind="requested",
                rid="r2",
                category="museum",
                tier=1,
                hours="08:30-17:00",
                dur=180,
                poi_id="m1_885978e4c8a2",
            ),
            _cand(
                "c3",
                "王府井大街",
                "北京",
                category="citywalk",
                tier=6,
                hours="08:00-22:00",
                dur=90,
            ),
            _cand(
                "c4",
                "景山公园",
                "北京",
                category="park",
                tier=8,
                hours="06:00-21:00",
                dur=60,
            ),
        ],
        "access_profiles": [copy.deepcopy(MUTIANYU_PROFILE)],
        "travel": [
            {"from_key": "m1_885978e4c8a2", "to_key": "poi_c3", "minutes": 10},
            {"from_key": "m1_885978e4c8a2", "to_key": "poi_c4", "minutes": 8},
            {"from_key": "poi_c3", "to_key": "poi_c4", "minutes": 15},
        ],
        "weather": [],
        "expect": [
            {"type": "requested_coverage", "args": {}},
            {
                "type": "remote_day_purity",
                "args": {
                    "name": "慕田峪长城",
                    "note": "C-06/C-15: no unrequested fill on the remote day",
                },
            },
            {
                "type": "no_entry_cap_breach",
                "args": {"caps": {"generic": "16:30", "big": "15:30"}},
            },
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": "remote-day exclusivity family (C-06/C-15 standalone)",
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v2.py",
            "note": "model side is green by construction (C-06 forbids fill "
            "on the remote day); fill placement is unrewarded pre-P1-D so "
            "the assertion may hold vacuously — the legacy replay side is "
            "where a B-03a/B-08 shape would surface.",
        },
    }


# --- g09 duration clamp (Q1) -------------------------------------------------


def build_g09() -> dict:
    """Duration family (B-19/Q1): park-type must with library duration 300 →
    typ clamps to 240 (F-15). span_cap ≤ 240 is the Q1 policy target."""
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": _request(
            1, ["北京"], [_must("r1", "颐和园", 5, "unesco_Q4132")], "2026-11-25"
        ),
        "candidates": [
            _cand(
                "c1",
                "颐和园",
                "北京",
                kind="requested",
                rid="r1",
                category="park",
                tier=2,
                hours="06:30-19:00",
                dur=300,
                poi_id="unesco_Q4132",
            ),
            _cand(
                "c2",
                "景山公园",
                "北京",
                category="park",
                tier=8,
                hours="06:00-21:00",
                dur=60,
            ),
        ],
        "access_profiles": [],
        "travel": [{"from_key": "unesco_Q4132", "to_key": "poi_c2", "minutes": 25}],
        "weather": [],
        "expect": [
            {"type": "requested_coverage", "args": {}},
            {
                "type": "span_cap",
                "args": {
                    "name": "颐和园",
                    "max_minutes": 240,
                    "note": "Q1: typ = min(library 300, 240) for park-type big sites",
                },
            },
            {
                "type": "no_entry_cap_breach",
                "args": {"caps": {"generic": "16:30", "big": "15:30"}},
            },
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": "duration family (B-19/Q1): 颐和园 300-min library row",
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v2.py",
            "note": "duration flexes in [low=120, library=300] (F-20) with no "
            "duration-lean objective until P1-D (F-23) — the deterministic "
            "solve currently sits at the tier minimum, so this passes today "
            "as a regression guard; if P1-D ever rewards longer stays the "
            "cap must still hold. Clamp disclosure (F-33) pends P1-F.",
        },
    }


# --- g10 multi-city coherence ------------------------------------------------


def build_g10() -> dict:
    """Multi-city family (C-07): 上海×2 + 杭州×1, musts in both cities; no
    day may mix cities."""
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": _request(
            3,
            ["上海", "杭州"],
            [
                _must("r1", "外滩", 5, "ct_上海_20"),
                _must("r2", "豫园", 4, "ct_上海_21"),
                _must("r3", "西湖风景名胜区", 5, "unesco_WestLake"),
            ],
            "2026-11-25",
        ),
        "candidates": [
            _cand(
                "c1",
                "外滩",
                "上海",
                kind="requested",
                rid="r1",
                tier=1,
                dur=90,
                poi_id="ct_上海_20",
            ),
            _cand(
                "c2",
                "豫园",
                "上海",
                kind="requested",
                rid="r2",
                tier=2,
                dur=90,
                poi_id="ct_上海_21",
            ),
            _cand(
                "c3",
                "西湖风景名胜区",
                "杭州",
                kind="requested",
                rid="r3",
                category="park",
                tier=1,
                dur=180,
                poi_id="unesco_WestLake",
            ),
            _cand("c4", "南京路步行街", "上海", category="citywalk", tier=6, dur=90),
            _cand("c5", "田子坊", "上海", category="citywalk", tier=7, dur=75),
            _cand("c6", "清河坊", "杭州", category="citywalk", tier=7, dur=75),
            _cand("c7", "断桥残雪", "杭州", category="sight", tier=5, dur=60),
        ],
        "access_profiles": [],
        "travel": [],
        "weather": [],
        "expect": [
            {"type": "requested_coverage", "args": {}},
            {"type": "city_coherence", "args": {"note": "C-07: no day mixes cities"}},
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": "multi-city family (C-07): 上海+杭州 3 天",
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v2.py",
            "note": "city order across days is an intent-layer input (Q6); "
            "this scenario pins only the per-day single-city invariant.",
        },
    }


# --- g11 trip-scale convergence (Q3) ----------------------------------------


def build_g11() -> dict:
    """Trip-scale family (Q3): 5 days, 2 cities, 6 musts, 30 candidates —
    the convergence-within-budget anchor for the P2-B gate."""
    bj_fills: list[dict] = []
    sh_fills: list[dict] = []
    for i in range(12):
        bj_fills.append(
            _cand(
                "b%d" % (i + 1),
                "北京城区点位%02d" % (i + 1),
                "北京",
                category="museum" if i % 2 == 0 else "sight",
                tier=9 + (i % 3),
                lon=116.30 + 0.02 * (i % 6),
                lat=39.90 + 0.015 * (i // 6),
                hours="09:00-17:00",
                dur=75,
            )
        )
        sh_fills.append(
            _cand(
                "s%d" % (i + 1),
                "上海城区点位%02d" % (i + 1),
                "上海",
                category="museum" if i % 2 == 0 else "sight",
                tier=9 + (i % 3),
                lon=121.44 + 0.02 * (i % 6),
                lat=31.20 + 0.015 * (i // 6),
                hours="09:00-17:00",
                dur=75,
            )
        )
    candidates = [
        _cand(
            "c1",
            "故宫博物院",
            "北京",
            kind="requested",
            rid="r1",
            category="museum",
            tier=1,
            hours="08:30-17:00",
            dur=180,
            poi_id="m1_885978e4c8a2",
        ),
        _cand(
            "c2",
            "慕田峪长城",
            "北京",
            kind="requested",
            rid="r2",
            category="historic",
            tier=1,
            hours="08:00-17:30",
            dur=180,
            remote=True,
            poi_id="ct_北京_8",
        ),
        _cand(
            "c3",
            "颐和园",
            "北京",
            kind="requested",
            rid="r3",
            category="park",
            tier=2,
            hours="06:30-19:00",
            dur=300,
            poi_id="unesco_Q4132",
        ),
        _cand(
            "c4",
            "外滩",
            "上海",
            kind="requested",
            rid="r4",
            tier=1,
            dur=90,
            poi_id="ct_上海_20",
        ),
        _cand(
            "c5",
            "豫园",
            "上海",
            kind="requested",
            rid="r5",
            tier=2,
            dur=90,
            poi_id="ct_上海_21",
        ),
        _cand(
            "c6",
            "东方明珠",
            "上海",
            kind="requested",
            rid="r6",
            tier=4,
            hours="08:30-19:30",
            dur=90,
            poi_id="ct_上海_1",
        ),
        *bj_fills,
        *sh_fills,
    ]
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": _request(
            5,
            ["北京", "上海"],
            [
                _must("r1", "故宫博物院", 5, "m1_885978e4c8a2"),
                _must("r2", "慕田峪长城", 4, "ct_北京_8"),
                _must("r3", "颐和园", 3, "unesco_Q4132"),
                _must("r4", "外滩", 5, "ct_上海_20"),
                _must("r5", "豫园", 4, "ct_上海_21"),
                _must("r6", "东方明珠", 3, "ct_上海_1"),
            ],
            "2026-11-25",
        ),
        "candidates": candidates,
        "access_profiles": [copy.deepcopy(MUTIANYU_PROFILE)],
        "travel": [],
        "weather": [],
        "expect": [
            {
                "type": "requested_coverage",
                "args": {"note": "all six musts covered at trip scale"},
            },
            {
                "type": "no_entry_cap_breach",
                "args": {"caps": {"generic": "16:30", "big": "15:30"}},
            },
            {"type": "city_coherence", "args": {"note": "C-07 at trip scale"}},
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": "trip-scale family (Q3): 5 days × 2 cities × 30 candidates",
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v2.py",
            "note": "the convergence gate (OPTIMAL/FEASIBLE within the 3 s "
            "budget) is measured by the harness on this scenario — Q3 "
            "evidence for P3. Synthetic point names are deliberate: they "
            "must not collide with real library rows.",
        },
    }


# --- g12 closed weekday (C-01) ----------------------------------------------


def build_g12() -> dict:
    """Closed-day family (C-01): start on a Monday; the museum row closes
    Mondays → must be unplaced+disclosed, never silently dropped."""
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": _request(
            1,
            ["北京"],
            [
                _must("r1", "中国国家博物馆", 5, "ct_北京_30"),
                _must("r2", "天坛", 4, "unesco_Q125445"),
            ],
            "2026-11-23",
        ),
        "candidates": [
            _cand(
                "c1",
                "中国国家博物馆",
                "北京",
                kind="requested",
                rid="r1",
                category="museum",
                tier=1,
                hours="周二至周日09:00-17:00,周一关闭",
                dur=150,
                poi_id="ct_北京_30",
            ),
            _cand(
                "c2",
                "天坛",
                "北京",
                kind="requested",
                rid="r2",
                category="temple",
                tier=1,
                hours="06:30-22:00",
                dur=150,
                poi_id="unesco_Q125445",
            ),
        ],
        "access_profiles": [],
        "travel": [
            {"from_key": "ct_北京_30", "to_key": "unesco_Q125445", "minutes": 12}
        ],
        "weather": [],
        "expect": [
            {
                "type": "requested_coverage",
                "args": {
                    "note": "closed-day must must surface as unplaced, never silent"
                },
            },
            {
                "type": "no_entry_cap_breach",
                "args": {"caps": {"generic": "16:30", "big": "15:30"}},
            },
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": "closed-day family (C-01): 周一关闭 museum on a Monday start",
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v2.py",
            "note": "unplaced reason wording (F-26 certificate) pends P1-E; "
            "coverage via the unplaced row is the B-01-proof shape now.",
        },
    }


# --- g13 content twins -------------------------------------------------------


def build_g13() -> dict:
    """Content-twin family (大足 incident 2026-10-31): museum + cinema rows
    share the 宝顶镇 cluster with the anchor site."""
    x, y = XY["大足石刻"]
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": _request(
            1, ["重庆"], [_must("r1", "大足石刻", 5, "5a_243")], "2026-11-25"
        ),
        "candidates": [
            _cand(
                "c1",
                "大足石刻",
                "重庆",
                kind="requested",
                rid="r1",
                category="sight",
                tier=2,
                hours="08:30-18:00",
                dur=210,
                poi_id="5a_243",
            ),
            _cand(
                "c2",
                "大足石刻博物馆",
                "重庆",
                category="museum",
                tier=3,
                lon=x + 0.004,
                lat=y + 0.003,
                hours="09:00-16:30",
                dur=90,
            ),
            _cand(
                "c3",
                "大足石刻数字影院",
                "重庆",
                category="entertainment",
                tier=6,
                lon=x + 0.005,
                lat=y + 0.002,
                hours="10:00-17:00",
                dur=60,
            ),
        ],
        "access_profiles": [],
        "travel": [
            {"from_key": "5a_243", "to_key": "poi_c2", "minutes": 8},
            {"from_key": "5a_243", "to_key": "poi_c3", "minutes": 10},
            {"from_key": "poi_c2", "to_key": "poi_c3", "minutes": 6},
        ],
        "weather": [],
        "expect": [
            {"type": "requested_coverage", "args": {}},
            {
                "type": "no_entry_cap_breach",
                "args": {"caps": {"generic": "16:30", "big": "15:30"}},
            },
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": "content-twin family (大足 2026-10-31 博物馆+影院)",
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v2.py",
            "note": "no twin constraint exists pre-P1-D — the model may place "
            "both twins; the diff report surfaces the gap and the twin rule "
            "(C-16 diversity caps / F-23) burns it down. Scenario committed "
            "before the fix, per the P2-B rule.",
        },
    }


# --- g14 per-city day windows (C-17, R8-S2) -----------------------------------


def build_g14() -> dict:
    """分城天数（口径 A）：出发城+双目的地，city_days 杭州2/上海3；
    杭州锁日 1-2、上海锁日 3-5，出发城与窗外候选灭活（legacy 拆窗镜像）。"""
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": _request(
            5,
            ["北京", "杭州", "上海"],
            [
                _must("r1", "西湖风景名胜区", 5, "unesco_WestLake"),
                _must("r2", "灵隐寺", 4, "ct_杭州_01"),
                _must("r3", "外滩", 5, "ct_上海_20"),
                _must("r4", "豫园", 4, "ct_上海_21"),
            ],
            "2026-11-25",
            city_days={"杭州": 2, "上海": 3},
        ),
        "candidates": [
            _cand(
                "c1",
                "西湖风景名胜区",
                "杭州",
                kind="requested",
                rid="r1",
                tier=1,
                dur=90,
                poi_id="unesco_WestLake",
            ),
            _cand(
                "c2",
                "灵隐寺",
                "杭州",
                kind="requested",
                rid="r2",
                tier=1,
                dur=90,
                poi_id="ct_杭州_01",
            ),
            _cand(
                "c3",
                "外滩",
                "上海",
                kind="requested",
                rid="r3",
                tier=1,
                dur=90,
                poi_id="ct_上海_20",
            ),
            _cand(
                "c4",
                "豫园",
                "上海",
                kind="requested",
                rid="r4",
                tier=1,
                dur=75,
                poi_id="ct_上海_21",
            ),
            _cand("c5", "河坊街", "杭州", kind="fill", tier=3, dur=60),
            _cand("c6", "南京路步行街", "上海", kind="fill", tier=3, dur=60),
            _cand("c7", "故宫博物院", "北京", kind="fill", tier=1, dur=120),
        ],
        "access_profiles": [],
        "travel": [],
        "weather": [],
        "expect": [
            {"type": "requested_coverage", "args": {}},
            {"type": "city_coherence", "args": {"note": "C-07 + C-17 windows"}},
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": "R8-S2 分城天数（2026-11-18 拍板「全量切引擎」口径 A）",
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v2.py",
            "note": (
                "city_days 杭州2/上海3：杭州日窗 1-2、上海日窗 3-5；出发城"
                "（北京）不占活动窗——legacy _split_days 的模型镜像（C-17）。"
            ),
        },
    }


# --- g15 food must meal card (R8-S2b) ----------------------------------------


def build_g15() -> dict:
    """餐类必去：真餐厅 any-槽（模型自选午/晚、顶餐卡不双渲染）。"""
    return {
        "schema_version": 2,
        "source": "golden-fixture",
        "library_version": "poi-snapshot-2026-11-17",
        "request": _request(
            1,
            ["上海"],
            [
                _must("r1", "外滩", 5, "ct_上海_20"),
                _must("r2", "福和慧", 4, "ct_上海_food_1"),
            ],
            "2026-11-25",
        ),
        "candidates": [
            _cand(
                "c1",
                "外滩",
                "上海",
                kind="requested",
                rid="r1",
                tier=1,
                dur=90,
                poi_id="ct_上海_20",
            ),
            {
                **_cand(
                    "c2",
                    "福和慧",
                    "上海",
                    kind="requested",
                    rid="r2",
                    tier=2,
                    dur=60,
                    hours="11:00-20:30",
                    poi_id="ct_上海_food_1",
                    category="food",
                ),
                "meal_slot": "any",
            },
            _cand("c3", "豫园", "上海", kind="fill", tier=2, dur=75),
        ],
        "access_profiles": [],
        "travel": [],
        "weather": [],
        "expect": [
            {"type": "requested_coverage", "args": {}},
            {"type": "deterministic", "args": {"runs": 2}},
        ],
        "provenance": {
            "incident": (
                "R8-S2b 餐类必去（2026-11-18 拍板「餐类必去需要 CP-SAT 能处理」）"
            ),
            "built_at": "2026-11-18",
            "builder": "tests/golden/build_corpus_v2.py",
            "note": (
                "真餐厅 any-槽：C-09 自选午/晚、顶系统餐卡（命名卡=餐厅本体），"
                "装配不双渲染；另一槽照常出占位餐卡。"
            ),
        },
    }


def main() -> int:
    with open(G01, "r", encoding="utf-8") as fh:
        base = json.load(fh)
    _write("g05_rain_rebalance.json", build_g05(base))
    _write("g06_reopen_pins.json", build_g06(base))
    _write("g07_name_variants.json", build_g07(base))
    _write("g08_remote_exclusive.json", build_g08())
    _write("g09_duration_clamp.json", build_g09())
    _write("g10_city_coherence.json", build_g10())
    _write("g11_trip_scale.json", build_g11())
    _write("g12_closed_weekday.json", build_g12())
    _write("g13_twin_content_dup.json", build_g13())
    _write("g14_city_days_windows.json", build_g14())
    _write("g15_food_must_meal_card.json", build_g15())
    return 0


if __name__ == "__main__":
    sys.exit(main())
