"""P3 seam tests: live snapshot builder + flag-gated session generator."""

from __future__ import annotations

from app.services.trip_solver.live import (
    bilingual_weather,
    generate_session_via_trip_solver,
    snapshot_from_request,
)
from app.services.trip_solver.shadow.replay import SnapshotStore
from app.services.trip_solver.types import CandidateItem, validate_snapshot


def _rows():
    def row(
        name,
        city,
        *,
        lon=121.47,
        lat=31.23,
        cat="sight",
        tier=6,
        hours="09:00-18:00",
        pid=None,
    ):
        return {
            "id": pid or ("poi_%s" % name),
            "name": name,
            "city": city,
            "category": cat,
            "location": (lon, lat),
            "opening_hours": hours,
            "best_visit_time": "any",
            "suggested_duration_min": 90,
            "indoor": None,
            "rain_ok": None,
            "tags": [],
            "source": "test",
            "rating": None,
            "rating_count": 0,
            "_tier": tier,
            "status": "active",
        }

    return [
        row("外滩", "上海", pid="ct_上海_20", tier=1, lon=121.4903, lat=31.2335),
        row("豫园", "上海", pid="ct_上海_21", tier=2, lon=121.4921, lat=31.2273),
        row("南京路步行街", "上海", cat="citywalk", tier=6, lon=121.4756, lat=31.2334),
    ]


def _store():
    return SnapshotStore(
        [
            CandidateItem(
                cid="c1",
                name=name,
                poi_id=pid,
                city="上海",
                category=cat,
                tier=tier,
                lon=lon,
                lat=lat,
                opening_hours=hours,
                suggested_duration_min=90,
            )
            for name, cat, tier, lon, lat, hours, pid in [
                ("外滩", "sight", 1, 121.4903, 31.2335, "09:00-21:00", "ct_上海_20"),
                ("豫园", "sight", 2, 121.4921, 31.2273, "09:00-18:00", "ct_上海_21"),
                (
                    "南京路步行街",
                    "citywalk",
                    6,
                    121.4756,
                    31.2334,
                    "10:00-22:00",
                    "ct_上海_22",
                ),
            ]
        ]
    )


def test_snapshot_binds_musts_and_pool():
    snap = snapshot_from_request(
        cities=["上海"],
        days=2,
        start_date="2026-11-25",
        musts=["外滩"],
        store=_store(),
    )
    assert snap.schema_version == 2
    assert validate_snapshot(snap) == []
    must = snap.request.musts[0]
    assert must.name == "外滩" and must.poi_id == "ct_上海_20"
    kinds = {c.name: c.kind for c in snap.candidates}
    assert kinds["外滩"] == "requested"
    assert kinds["豫园"] == "fill" and kinds["南京路步行街"] == "fill"


def test_unbindable_must_gets_skeleton_not_silent_drop():
    snap = snapshot_from_request(
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["不存在的点"],
        store=_store(),
    )
    assert validate_snapshot(snap) == []  # skeleton keeps the request legal
    assert any(
        c.name == "不存在的点" and c.kind == "requested" for c in snap.candidates
    )


def test_avoid_excludes_pool_rows():
    snap = snapshot_from_request(
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["外滩"],
        store=_store(),
        avoid=["南京路步行街"],
    )
    assert not any(c.name == "南京路步行街" for c in snap.candidates)


def test_access_profile_binds_pool_row():
    service = {
        "poi_name": "豫园",
        "boarding_stop": "人民广场",
        "outbound_times": [8 * 60 + 30, 9 * 60 + 30],
        "return_times": [16 * 60 + 30],
        "ride_minutes": 40,
        "last_mile_minutes": 5,
        "fare_cny": 20,
        "operator": "测试专线",
    }
    snap = snapshot_from_request(
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["豫园"],
        store=_store(),
        service_rows=[service],
    )
    assert len(snap.access_profiles) == 1
    profile = snap.access_profiles[0]
    assert profile.to_poi == "ct_上海_21" and profile.departures == ("08:30", "09:30")
    yuyuan = next(c for c in snap.candidates if c.name == "豫园")
    assert yuyuan.remote is True


def test_weather_bilingualised():
    assert bilingual_weather("小雨") == "小雨 (rain)"
    assert bilingual_weather("大雨") == "大雨 (heavy rain)"
    assert bilingual_weather("晴") == "晴"


def test_generator_flag_gates():
    store = _store()
    out = generate_session_via_trip_solver(
        device_id="t",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["外滩"],
        store=store,
    )
    assert out == (None, None)  # default flag = legacy → seam dormant


def test_generator_serves_when_cpsat(monkeypatch):
    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session, outcome = generate_session_via_trip_solver(
        device_id="t",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["外滩"],
        store=_store(),
    )
    assert outcome is not None and outcome.engine == "cpsat"
    assert session is not None and session.plan is not None
    assert session.state == "ready"
    assert session.plan.days


def test_generator_passes_lang_to_session(monkeypatch):
    """二期：语言随缝透传（EN 用户不再被默认成 zh）。"""
    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session, outcome = generate_session_via_trip_solver(
        device_id="t",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["外滩"],
        store=_store(),
        lang="en",
    )
    assert session is not None and session.lang == "en"
