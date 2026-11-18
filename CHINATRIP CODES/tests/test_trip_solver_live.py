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


def _pref_store():
    return SnapshotStore(
        [
            CandidateItem(
                cid="p%d" % i,
                name=name,
                poi_id="poi_%d" % i,
                city="上海",
                category=cat,
                tier=tier,
                lon=121.47 + i * 0.01,
                lat=31.23,
                opening_hours="09:00-18:00",
                suggested_duration_min=90,
            )
            for i, (name, cat, tier) in enumerate(
                [
                    ("中山公园", "park", 1),
                    ("静安寺", "temple", 2),
                    ("复兴公园", "park", 3),
                    ("上海美术馆", "art", 4),
                ]
            )
        ]
    )


def test_pool_boost_pulls_preferred_category_into_pool():
    """R8：偏好非空 → 2× 取数 + 偏好命中稳定前置（组内保库序）截回
    limit——legacy「偏好位在 tier 之前」的池侧同款；偏好为空零变化。"""
    snap = snapshot_from_request(
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=[],
        store=_pref_store(),
        preferences="喜欢博物馆人文",
        pool_limit=2,
    )
    names = [c.name for c in snap.candidates if c.kind == "fill"]
    assert "上海美术馆" in names  # tier4 借偏好进池

    ctrl = snapshot_from_request(
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=[],
        store=_pref_store(),
        preferences="",
        pool_limit=2,
    )
    ctrl_names = [c.name for c in ctrl.candidates if c.kind == "fill"]
    assert "上海美术馆" not in ctrl_names


def test_replan_session_via_trip_solver_mutates_in_place(monkeypatch):
    """R8：会话级重解——session_id/history 保留、plan 就位、偏好文本
    进快照；旗关 = None（legacy 零变化）。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import replan_session_via_trip_solver

    session = PlanSession(
        session_id="sess-r8",
        device_id="d8",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        must_visits=["外滩"],
        preferences="喜欢博物馆人文",
    )
    out = replan_session_via_trip_solver(
        session, store=_store(), extra_assumptions=["已按偏好重排"]
    )
    assert out is None  # default flag=legacy → 钩子静默
    assert session.plan is None

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    out2 = replan_session_via_trip_solver(
        session, store=_store(), extra_assumptions=["已按偏好重排"]
    )
    assert out2 is not None and out2.engine == "cpsat"
    assert session.plan is not None and session.state == "ready"
    assert session.session_id == "sess-r8"
    assert "已按偏好重排" in session.assumptions
