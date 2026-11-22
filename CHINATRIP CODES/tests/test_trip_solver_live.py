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


def test_access_profiles_for_real_store_shapes():
    # R13c/R13c2（2026-11-19）：真库 PoiDetailStore 行 id 键=source_poi_id、
    # 班次是 '07:30' 字符串——两种形态都必须能绑（此前 live 接驳档案
    # 恒空：C-08 班次约束空转、引擎去程/回城卡永不渲染）。
    from app.services.trip_solver.live import _access_profiles_for

    pool = [{"name": "慕田峪长城", "source_poi_id": "ct_北京_8"}]
    svc = {
        "poi_name": "慕田峪长城",
        "boarding_stop": "前门大街北口",
        "outbound_times": ["07:30", "08:30"],
        "return_times": ["14:30"],
        "ride_minutes": 90,
        "last_mile_minutes": 8,
    }
    profiles = _access_profiles_for(pool, [svc])
    assert len(profiles) == 1
    p = profiles[0]
    assert p.to_poi == "ct_北京_8"
    assert p.departures == ("07:30", "08:30")
    assert p.returns == ("14:30",)
    assert p.ride_minutes == 90


def test_edit_session_not_ready_returns_disclosed_fallback(monkeypatch):
    """R13h：编辑缝与 generate/replan 同口径——cpsat 旗下未就绪返回
    披露型 fallback outcome，绝不裸 (None, None) 静默落 legacy 修复
    （R12 救援契约第 4 缝；调用方 agent/plan.py 已读 outcome 补留痕）。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver import entry as entry_mod
    from app.services.trip_solver.live import edit_session_via_trip_solver

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    # 编辑缝是函数内 from .entry import serving_ready——patch 源头
    monkeypatch.setattr(entry_mod, "serving_ready", lambda: (False, "not-ready-test"))
    session = PlanSession(
        session_id="sess-fb",
        device_id="dfb",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        must_visits=["外滩"],
    )
    plan, outcome = edit_session_via_trip_solver(
        session, store=_store(), ops=[{"kind": "move", "name": "外滩", "day": 1}]
    )
    assert plan is None
    assert outcome is not None and outcome.fallback is True
    assert outcome.disclosures


def test_same_poi_musts_bind_single_candidate(monkeypatch):
    """R13h：同 POI 双必去（裂词/别名同点异名）只绑一张 requested 候选
    ——此前两张候选同点双卡可行（C-03 零车程不禁双在场）。"""
    from app.services.trip_solver.live import snapshot_from_request

    snap = snapshot_from_request(
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["豫园", "豫园"],
        store=_store(),
    )
    yuyuan = [c for c in snap.candidates if c.name == "豫园"]
    assert len(yuyuan) == 1
    assert yuyuan[0].kind == "requested"


def test_session_snapshot_weather_passthrough(monkeypatch):
    """R13j：重解/编辑缝的快照重建透传 weather_lookup——此前三缝
    （start/restart/_session_snapshot）全不传，live 引擎雨天约束恒空转
    （legacy 有天气/corpus 有 baked 天气、唯独 live 引擎瞎排雨天）。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import _session_snapshot

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session = PlanSession(
        session_id="sess-wx",
        device_id="dwx",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        must_visits=["外滩"],
    )
    calls = []

    def fake_weather(city, iso):
        calls.append((city, iso))
        return "小雨"

    snap = _session_snapshot(session, _store(), weather_lookup=fake_weather)
    assert snap is not None
    assert calls, "weather_lookup must be invoked during snapshot rebuild"
    assert snap.weather, "snapshot must carry weather rows for the engine"


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


def test_generator_harvests_named_musts_from_preferences(monkeypatch):
    """R13f（2026-11-19「fix all」收口实测）：start 缝 preferences 里的
    强意图点名词（必去/要去/打卡…）折进 musts 硬覆盖——此前只当软偏
    好，接驳档案生效后远郊成本变真，引擎合法不选=用户必去意图静默丢
    失（live 实锤：必去慕田峪长城无墙无披露）。「想去」仍留软偏好。"""
    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session, outcome = generate_session_via_trip_solver(
        device_id="t-r13f",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=[],
        store=_store(),
        preferences="必去豫园",
    )
    assert outcome is not None and outcome.engine == "cpsat"
    assert session is not None and session.plan is not None
    names = [it.name for day in session.plan.days for it in day.items]
    assert any("豫园" in (n or "") for n in names) or any(
        "豫园" in str(u.get("name")) for u in session.plan.unplaced
    )


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


# ---------- R8-S2b: food must binding ----------


def test_food_must_binds_meal_slot_any():
    from app.services.trip_solver.live import snapshot_from_request
    from app.services.trip_solver.shadow.replay import SnapshotStore
    from app.services.trip_solver.types import CandidateItem

    store = SnapshotStore(
        [
            CandidateItem(
                cid="c1",
                name="外滩",
                poi_id="ct_上海_20",
                city="上海",
                category="sight",
                tier=1,
                opening_hours="09:00-21:00",
                suggested_duration_min=90,
            ),
            CandidateItem(
                cid="c2",
                name="福和慧",
                poi_id="ct_上海_food_1",
                city="上海",
                category="food",
                tier=2,
                opening_hours="11:00-20:30",
                suggested_duration_min=90,
            ),
        ]
    )
    snapshot = snapshot_from_request(
        cities=["上海"],
        days=1,
        start_date=None,
        musts=["福和慧"],
        store=store,
    )
    bound = [c for c in snapshot.candidates if c.rid]
    assert len(bound) == 1
    assert bound[0].category == "food"
    assert bound[0].meal_slot == "any"  # R8-S2b 真餐厅 any-槽


def test_replan_preserves_pinned_cards_exact_slot(monkeypatch):
    """R8b 钉位保全（铁律 19 全保位）：钉卡按 C-04 钉死日+时刻——
    重排后同日同时刻原地不动。"""
    from datetime import time as _time

    from app.services.agent.plan import PlanSession
    from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
    from app.services.trip_solver.live import replan_session_via_trip_solver

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    card = VisitItem(
        item_id="v1",
        name="外滩",
        city="上海",
        day=1,
        start_time=_time(10, 0),
        end_time=_time(11, 30),
        duration_minutes=90,
        pinned=True,
        category="sight",
    )
    plan = ItineraryPlan(
        itinerary_id="it-pin",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=[card])],
    )
    plan.assumptions = []
    session = PlanSession(
        session_id="sess-pin",
        device_id="dp",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        must_visits=[],
        preferences="",
        plan=plan,
    )
    outcome = replan_session_via_trip_solver(session, store=_store())
    assert outcome is not None and outcome.engine == "cpsat"
    placed = [
        it
        for d in session.plan.days
        for it in d.items
        if getattr(it, "name", "") == "外滩"
    ]
    assert placed, "pinned card must stay present"
    assert placed[0].day == 1
    assert placed[0].start_time.hour == 10
    assert placed[0].start_time.minute == 0


def test_degenerate_plan_falls_back_to_legacy(monkeypatch):
    """R8b-2（成都空天事故）：池瞬态损坏导致空天/零观光 → 缝回落
    legacy + 披露，绝不交付空行程。"""
    from app.services.trip_solver.shadow.replay import SnapshotStore
    from app.services.trip_solver.types import CandidateItem

    # 坏池：仅 1 行 food 候选（观光 0）——求解可 FEASIBLE 但零观光
    bad = SnapshotStore(
        [
            CandidateItem(
                cid="f1",
                name="某餐厅",
                poi_id="poi_food1",
                city="上海",
                category="food",
                tier=5,
                lon=121.47,
                lat=31.23,
                opening_hours="09:00-21:00",
                suggested_duration_min=60,
            )
        ]
    )
    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session, outcome = generate_session_via_trip_solver(
        device_id="t",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=[],
        store=bad,
    )
    # 缝要么因池形态回落（None+None），要么解出退化计划被闸回落——
    # 两种合法形态都不得交付 session
    if outcome is not None:
        assert session is None
        assert outcome.fallback is True
        assert outcome.disclosures
    else:
        assert session is None


def test_degenerate_plan_detector_unit():
    from datetime import time as _time

    from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
    from app.services.trip_solver.live import _degenerate_plan

    full = ItineraryPlan(
        itinerary_id="it-x",
        cities=["上海"],
        days=[
            DayPlan(
                day=1,
                base_city="上海",
                items=[
                    VisitItem(
                        item_id="v1",
                        name="外滩",
                        city="上海",
                        day=1,
                        start_time=_time(9),
                        end_time=_time(10),
                        duration_minutes=60,
                    )
                ],
            )
        ],
    )
    assert _degenerate_plan(full) is False
    empty_day = ItineraryPlan(
        itinerary_id="it-y",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=[])],
    )
    assert _degenerate_plan(empty_day) is True
    assert _degenerate_plan(None) is True


# ---------- R8-S4: pool quota + all-fill regression ----------


def test_pool_quota_scales_with_trip_shape():
    from app.services.trip_solver.live import snapshot_from_request

    snap_a = snapshot_from_request(
        cities=["北京", "杭州", "上海"],
        days=5,
        start_date=None,
        musts=[],
        store=_store(),
    )
    cities_a: dict = {}
    for c in snap_a.candidates:
        cities_a[c.city or "?"] = cities_a.get(c.city or "?", 0) + 1
    assert sum(cities_a.values()) <= 42  # 总量 ≈ days×7（35±圆整上浮）
    snap_b = snapshot_from_request(
        cities=["北京", "杭州", "上海"],
        days=5,
        start_date=None,
        musts=[],
        store=_store(),
        city_days={"杭州": 2, "上海": 3},
    )
    cities_b = {c.city for c in snap_b.candidates}
    assert "北京" not in cities_b  # 有分城：出发城不取数（C-17 灭活对齐）


def test_all_fill_multi_city_places_fills(monkeypatch):
    """R8-S4 回归：多城 all-fill（musts=[]）不得空排——池配额+种子时机修。"""

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    from app.services.trip_solver.live import generate_session_via_trip_solver
    from app.services.trip_solver.shadow.replay import SnapshotStore
    from app.services.trip_solver.types import CandidateItem

    rows = []
    for i in range(10):
        rows.append(
            CandidateItem(
                cid="h%d" % i,
                name="杭州点%d" % i,
                poi_id="p_h%d" % i,
                city="杭州",
                category="sight",
                tier=(i % 5) + 1,
                lon=120.0 + i * 0.01,
                lat=30.2 + i * 0.01,
                opening_hours="08:00-18:00",
                suggested_duration_min=90,
            )
        )
        rows.append(
            CandidateItem(
                cid="s%d" % i,
                name="上海点%d" % i,
                poi_id="p_s%d" % i,
                city="上海",
                category="sight",
                tier=(i % 5) + 1,
                lon=121.4 + i * 0.01,
                lat=31.2 + i * 0.01,
                opening_hours="08:00-18:00",
                suggested_duration_min=90,
            )
        )
    session, outcome = generate_session_via_trip_solver(
        device_id="t-allfill",
        cities=["杭州", "上海"],
        days=2,
        start_date="2026-11-25",
        musts=[],
        store=SnapshotStore(rows),
    )
    assert session is not None
    total = sum(len(d.items) for d in session.plan.days)
    assert total >= 6  # 空排=回归失败


def test_replan_honors_comment_day_start_floor(monkeypatch):
    """R9-1：brief「LEAVE HOTEL ON 11AM」语义随缝入模——C-04 day1
    地板（重排后首观光 ≥ 指定时刻）。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import replan_session_via_trip_solver

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session = PlanSession(
        session_id="sess-d1s",
        device_id="dd",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["外滩"],
        preferences="",
        comment_day_start="11:00",
    )
    outcome = replan_session_via_trip_solver(session, store=_store())
    assert outcome is not None and outcome.engine == "cpsat"
    starts = [
        it.start_time
        for d in session.plan.days
        for it in d.items
        if getattr(it, "start_time", None) is not None
        and (it.category or "") not in ("food", "hotel")
    ]
    assert starts
    assert all(st.hour >= 11 for st in starts)


def test_replan_folds_created_sites_as_musts(monkeypatch):
    """R9-1（拍板「复杂开局也走 CP-SAT」）：自造点折必去——库内绑定
    排入（外滩在库）；库外骨架兜底不吞点。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import replan_session_via_trip_solver

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session = PlanSession(
        session_id="sess-cs",
        device_id="dc",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=[],
        preferences="",
        created_sites=["外滩", "用户自造点XYZ"],
    )
    outcome = replan_session_via_trip_solver(session, store=_store())
    assert outcome is not None and outcome.engine == "cpsat"
    names = [it.name for d in session.plan.days for it in d.items]
    assert "外滩" in names  # 库内自造点=绑定排入
    # 库外自造点：骨架卡或 unplaced 披露（B-01 缝不吞点——绝不静默蒸发）
    unplaced = [u.name for u in (session.plan.unplaced or [])]
    assert ("用户自造点XYZ" in names) or ("用户自造点XYZ" in unplaced)


def test_intake_day_no_helper():
    from app.services.trip_solver.live import _intake_day_no

    # 端点日 → None（=引擎默认形状，hash 兼容）
    assert _intake_day_no("2026-11-25", "2026-11-25", 3, 1) is None
    assert _intake_day_no("2026-11-27", "2026-11-25", 3, 3) is None
    assert _intake_day_no(None, "2026-11-25", 3, 1) is None
    # 中途 → 天序
    assert _intake_day_no("2026-11-26", "2026-11-25", 3, 1) == 2
    # R9-2 角色特定端点：到达的端点=首日（2 天行程 D2 到达=中途形状，
    # 不归 None——此前误判致 day2 地板蒸发）；离开的端点=末日（首日
    # 离开=中途）
    assert _intake_day_no("2026-11-26", "2026-11-25", 2, 1) == 2
    assert _intake_day_no("2026-11-25", "2026-11-25", 3, 3) == 1
    # 越界 → clamp 到界内（角色端点仍判形状：到达 clamp 末日=中途；离开
    # clamp 首日=中途）
    assert _intake_day_no("2026-11-30", "2026-11-25", 3, 1) == 3
    assert _intake_day_no("2026-11-20", "2026-11-25", 3, 3) == 1


def test_midtrip_arrival_day_floor(monkeypatch):
    """R9-2：到达落在第 2 天 14:00 → day2 首卡 ≥ 到达+缓冲（no-mode 150）；
    day1 全天窗不受影响（legacy 撤腿重排同语义）。"""
    from test_trip_solver_live import _pref_store  # noqa: F401

    from app.services.trip_solver.inputs.enrich import enrich
    from app.services.trip_solver.live import snapshot_from_request
    from app.services.trip_solver.model.solve import solve_snapshot

    snap = snapshot_from_request(
        cities=["上海"],
        days=2,
        start_date="2026-11-25",
        musts=[],
        store=_pref_store(),
        preferences="",
        arrival_time="12:00",
        arrival_day=2,
    )
    assert snap.request.arrival_day == 2
    sol = solve_snapshot(enrich(snap), budget_s=3.0)
    day2 = [i for i in sol.items if i.day == 2 and i.kind == "visit"]
    assert day2, "day2 must place visits"
    floor = 12 * 60 + 150  # arrival 12:00 + no-mode buffer
    assert all(i.start_min >= floor for i in day2)
    day1 = [i for i in sol.items if i.day == 1 and i.kind == "visit"]
    if day1:
        assert min(i.start_min for i in day1) < floor  # day1 不受地板影响


def _edit_store():
    from app.services.trip_solver.shadow.replay import SnapshotStore

    return SnapshotStore(
        [
            CandidateItem(
                cid="p%d" % i,
                name=name,
                poi_id="poi_%d" % i,
                city="上海",
                category=cat,
                tier=tier,
                lon=121.47 + i * 0.008,
                lat=31.23,
                opening_hours="09:00-18:00",
                suggested_duration_min=90,
            )
            for i, (name, cat, tier) in enumerate(
                [
                    ("外滩", "sight", 1),
                    ("豫园", "sight", 2),
                    ("南京路步行街", "citywalk", 6),
                    ("静安寺", "temple", 3),
                    ("复兴公园", "park", 5),
                    ("上海美术馆", "art", 4),
                ]
            )
        ]
    )


def test_edit_session_move_to_day(monkeypatch):
    """R10：move op → 引擎编辑重解——引擎生身计划（先 replan）上 move
    一张卡到指定日；其余卡 C-04 硬钉保形；退化不出。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import (
        edit_session_via_trip_solver,
        replan_session_via_trip_solver,
    )

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session = PlanSession(
        session_id="sess-e",
        device_id="de",
        cities=["上海"],
        days=2,
        start_date="2026-11-25",
        musts=["外滩", "豫园"],
        preferences="",
    )
    out = replan_session_via_trip_solver(session, store=_edit_store())
    assert out is not None and out.engine == "cpsat" and session.plan is not None
    before = [
        (it.name, it.day, it.start_time.strftime("%H:%M"))
        for d in session.plan.days
        for it in d.items
        if (it.category or "") not in ("food", "hotel")
        # R12：leg-bridge-* 是派生交通卡（随装配重生成），不是可挪 POI
        and not str(it.item_id or "").startswith("leg-bridge-")
    ]
    src = next((n, d) for n, d, _s in before if d == 1)
    moved_name, from_day = src
    target_day = 2
    new_plan, outcome = edit_session_via_trip_solver(
        session,
        store=_edit_store(),
        ops=[{"kind": "move", "name": moved_name, "day": target_day}],
    )
    assert new_plan is not None, "engine edit must serve on native plan"
    after = {
        (it.name, it.day): it.start_time.strftime("%H:%M")
        for d in new_plan.days
        for it in d.items
        if (it.category or "") not in ("food", "hotel")
    }
    assert any(d == target_day for (n, d) in after if n == moved_name), (
        moved_name,
        after,
    )
    # keep 钉设计（R12-H 修订）：必去卡日不动；非必去（池荐）卡在
    # 让位语义下可重排日或让位（披露），绝不消失于无形。
    for name, day, st in before:
        if name == moved_name:
            continue
        if (name, day) in after:
            continue
        assert any(n == name for (n, _d) in after) or any(
            name in str(d.get("zh") or "")
            for d in (getattr(outcome, "disclosures", []) or [])
        ), (name, day, after)


def test_edit_session_unmappable_op_returns_none(monkeypatch):
    """R10：库外卡（快照池匹不上）→ None → 调用方回落 legacy 修复。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import edit_session_via_trip_solver

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session = PlanSession(
        session_id="sess-e2",
        device_id="de2",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        must_visits=[],
        preferences="",
    )
    plan, outcome = edit_session_via_trip_solver(
        session,
        store=_store(),
        ops=[{"kind": "move", "name": "不存在的点", "poi_id": None, "day": 1}],
    )
    assert plan is None and outcome is None


def test_edit_session_duplicate_names_keep_guard(monkeypatch):
    """R10b 回归：重名卡守卫——同名孪生卡分布在两天时，同一 cid 的 keep
    曾要求 presence 在两天同时为 1（模型矛盾 INFEASIBLE → 编辑道静默
    回落 legacy）；守卫按 cid 去重（歧义=不钉）后 move 编辑照常服务。"""
    from app.services.agent.plan import PlanSession
    from app.services.itinerary.models import DayPlan, ItineraryPlan
    from app.services.trip_solver.live import (
        edit_session_via_trip_solver,
        replan_session_via_trip_solver,
    )

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session = PlanSession(
        session_id="sess-dup",
        device_id="ddup",
        cities=["上海"],
        days=2,
        start_date="2026-11-25",
        musts=["外滩", "豫园"],
        preferences="",
    )
    out = replan_session_via_trip_solver(session, store=_edit_store())
    assert out is not None and out.engine == "cpsat" and session.plan is not None

    # 重名卡构造：第一张已排观光卡 model_copy 成同名孪生卡放到另一天——
    # _seated_cards 会为同一 cid 产出两个 day 不同的 keep 候选
    seated = [
        it
        for d in session.plan.days
        for it in d.items
        if it.start_time is not None
        and (it.category or "") not in ("food", "hotel", "transport", "transfer")
    ]
    assert len(seated) >= 2
    dup = seated[0]
    twin_day = 2 if dup.day == 1 else 1
    twin = dup.model_copy(update={"item_id": dup.item_id + "-twin", "day": twin_day})
    session.plan = ItineraryPlan(
        itinerary_id=session.plan.itinerary_id,
        cities=list(session.plan.cities),
        days=[
            DayPlan(
                day=d.day,
                base_city=d.base_city,
                items=[twin, *d.items] if d.day == twin_day else list(d.items),
            )
            for d in session.plan.days
        ],
    )

    # 对另一张卡做 move 编辑：守卫生效（歧义 cid 不钉）→ 引擎照常服务，
    # 绝不因 keep 矛盾 INFEASIBLE 静默回落
    moved = next(it for it in seated if it.name != dup.name)
    target_day = 2 if moved.day == 1 else 1
    new_plan, outcome = edit_session_via_trip_solver(
        session,
        store=_edit_store(),
        ops=[{"kind": "move", "name": moved.name, "day": target_day}],
    )
    assert new_plan is not None, "duplicate-name keeps must not kill the engine edit"
    after = {
        it.name: it.day
        for d in new_plan.days
        for it in d.items
        if (it.category or "") not in ("food", "hotel", "transport", "transfer")
    }
    assert after.get(moved.name) == target_day


def test_dict_ops_to_diffops_name_ambiguity():
    """R10b 回归：池内同名多行=歧义——by_name 不收（只信 poi_id）；name-
    only op 返回 None（调用方回落 legacy），poi_id 命中照常映射。"""
    from app.services.trip_solver.live import _dict_ops_to_diffops
    from app.services.trip_solver.types import (
        CandidateItem,
        FactSnapshot,
        RequestedItem,
        TripRequest,
    )

    snapshot = FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=1,
            cities=("上海",),
            musts=(RequestedItem(rid="r1", name="外滩"),),
        ),
        candidates=(
            CandidateItem(
                cid="c1",
                name="外滩",
                poi_id="ct_上海_20",
                kind="requested",
                rid="r1",
            ),
            CandidateItem(cid="f1", name="外滩", poi_id="poi_f1", kind="fill"),
            CandidateItem(cid="f2", name="豫园", poi_id="ct_上海_21", kind="fill"),
        ),
    )
    # 同名两行（c1/f1 都叫「外滩」）：name-only op 不再按第一个同名错钉
    name_only = _dict_ops_to_diffops(
        snapshot, [{"kind": "move", "name": "外滩", "day": 2}]
    )
    assert name_only is None
    # poi_id 命中不受歧义影响
    ops = _dict_ops_to_diffops(
        snapshot,
        [{"kind": "move", "name": "外滩", "poi_id": "ct_上海_20", "day": 2}],
    )
    assert ops is not None and len(ops) == 1
    assert ops[0].kind == "move" and ops[0].cid == "c1" and ops[0].day == 2
    # 无歧义的 name 照常映射（守卫不误伤单行名）
    ops2 = _dict_ops_to_diffops(snapshot, [{"kind": "delete", "name": "豫园"}])
    assert ops2 is not None and ops2[0].kind == "delete" and ops2[0].cid == "f2"


# ---------- R12-M: pool food -> meal card（餐厅进餐卡，绝不与占位并列） ----------


class _FoodExemptStore(SnapshotStore):
    """top_pois 荐点豁免形态（2026-11-07 指令）：知名餐厅 food 行不被
    exclude_food 过滤照常入池——live 北京四季民福/提督实录的 store 侧
    形态（引擎池因此拿到 food 行）。"""

    def top_pois_in_city(
        self, city: str, limit: int = 30, *, exclude_food: bool = True
    ):
        return self._city_rows(city)[:limit]


def _duck_store():
    from app.services.trip_solver.types import CandidateItem

    return _FoodExemptStore(
        [
            CandidateItem(
                cid="c1",
                name="故宫博物院",
                poi_id="m1_885978e4c8a2",
                city="北京",
                category="museum",
                tier=1,
                lon=116.4097,
                lat=39.9255,
                opening_hours="08:30-17:00",
                suggested_duration_min=120,
            ),
            CandidateItem(
                cid="c2",
                name="四季民福烤鸭店（故宫店）",
                poi_id="ct_北京_food_1",
                city="北京",
                category="food",
                tier=1,
                lon=116.4028,
                lat=39.9146,
                opening_hours="10:30-22:30",
                suggested_duration_min=60,
            ),
            CandidateItem(
                cid="c3",
                name="景山公园",
                poi_id="ct_北京_2",
                city="北京",
                category="park",
                tier=2,
                lon=116.3965,
                lat=39.9259,
                opening_hours="06:00-20:00",
                suggested_duration_min=90,
            ),
        ]
    )


def test_pool_food_binds_meal_slot_any():
    """R12-M：池内 food 行（荐点豁免入池的知名餐厅）any-槽——与餐类必去
    （R8-S2b）同口径；观光行照旧无槽。北京四季民福 live 案回归锁。"""
    snapshot = snapshot_from_request(
        cities=["北京"],
        days=1,
        start_date=None,
        musts=["故宫博物院"],
        store=_duck_store(),
    )
    pool_food = [c for c in snapshot.candidates if c.category == "food"]
    assert pool_food, "food row must survive into the pool (exempt store)"
    assert all(c.meal_slot == "any" for c in pool_food)
    others = [c for c in snapshot.candidates if c.category != "food"]
    assert others and all(c.meal_slot is None for c in others)


def test_pool_food_lands_on_meal_card_not_visit(monkeypatch):
    """R12-M 端到端：池内知名餐厅被选中→顶替午/晚占位卡成命名餐卡；
    绝不再以观光卡形态与占位餐卡并列（2026-11-19 用户报告
    「烤鸭店和午餐卡并列」回归锁）。"""
    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    from app.services.trip_solver.entry import ENGINE_CPSAT, solve_trip

    snapshot = snapshot_from_request(
        cities=["北京"],
        days=1,
        start_date=None,
        musts=["故宫博物院"],
        store=_duck_store(),
    )
    outcome = solve_trip(snapshot, flag=ENGINE_CPSAT, budget_s=3.0)
    plan = getattr(outcome, "plan", None)
    assert plan is not None, "engine must serve the scenario"
    items = plan.days[0].items
    duck_cards = [i for i in items if "四季民福" in (i.name or "")]
    assert duck_cards, "pool food should be selected (fill reward)"
    duck = duck_cards[0]
    assert duck.item_id.startswith("meal-"), (
        "restaurant must render as the named meal card, got %s" % duck.item_id
    )
    assert duck.poi_id, "named meal card carries the restaurant POI"
    assert len(duck_cards) == 1, "no second (visit-shaped) duck card"
    placeholders = [i for i in items if (i.name or "") in ("午餐", "晚饭")]
    assert placeholders, "the other slot keeps its placeholder card"


# ---------- R12-M2: barriers 平手排序雷（双卡同时刻不崩） ----------


def test_compact_days_barrier_tie_does_not_crash():
    """R12-M2 排序雷回归锁：compact_days 的 barriers=sorted([(start, end,
    card)]) 元组第三位是 VisitItem——两张 barrier 卡同时刻（双渲染/重复
    卡形态）时 Python 平手比较卡对象直接 TypeError。key 只比前两位。"""
    from datetime import time as _time

    from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
    from app.services.trip_solver.assembly.materialize import compact_days
    from app.services.trip_solver.types import FactSnapshot, TripRequest

    meal = VisitItem(
        item_id="meal-lunch-1",
        name="午餐",
        category="food",
        city="北京",
        day=1,
        start_time=_time(12, 0),
        end_time=_time(13, 0),
        duration_minutes=60,
    )
    pin = VisitItem(
        item_id="v-pin",
        name="天坛",
        category="temple",
        city="北京",
        day=1,
        start_time=_time(12, 0),
        end_time=_time(13, 0),
        duration_minutes=60,
        pinned=True,
    )
    movable = VisitItem(
        item_id="v-m",
        name="景山公园",
        category="park",
        city="北京",
        day=1,
        start_time=_time(14, 0),
        end_time=_time(15, 30),
        duration_minutes=90,
    )
    plan = ItineraryPlan(
        itinerary_id="it-tie",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[meal, pin, movable])],
    )
    snapshot = FactSnapshot(
        schema_version=2,
        request=TripRequest(days=1, cities=("北京",)),
        candidates=(),
    )
    out = compact_days(plan, snapshot)  # 旧版此处直接 TypeError
    assert out is not None


def test_edit_session_add_op_places_new_must(monkeypatch):
    """R13-#2：add op → musts 注入道——引擎生身 2 天计划上 add 静安寺
    （池内点 poi_3；avoid 先把它挡出 fill 池，注入是落卡唯一来路）；
    新计划含静安寺卡，其余卡 keep 钉日不动。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import (
        edit_session_via_trip_solver,
        replan_session_via_trip_solver,
    )

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session = PlanSession(
        session_id="sess-add",
        device_id="dadd",
        cities=["上海"],
        days=2,
        start_date="2026-11-25",
        must_visits=["外滩", "豫园"],
        avoid_sites=["静安寺"],
        preferences="",
    )
    out = replan_session_via_trip_solver(session, store=_edit_store())
    assert out is not None and out.engine == "cpsat" and session.plan is not None
    seated_before = [
        (it.name, it.day)
        for d in session.plan.days
        for it in d.items
        if (it.category or "") not in ("food", "hotel", "transport", "transfer")
        # R12：leg-bridge-* 是派生交通卡（随装配重生成），不是可挪 POI
        and not str(it.item_id or "").startswith("leg-bridge-")
    ]
    assert all(n != "静安寺" for n, _d in seated_before)
    new_plan, outcome = edit_session_via_trip_solver(
        session,
        store=_edit_store(),
        ops=[{"kind": "add", "name": "静安寺", "poi_id": "poi_3"}],
    )
    assert new_plan is not None, "engine add edit must serve on native plan"
    seated_after = [
        (it.name, it.day)
        for d in new_plan.days
        for it in d.items
        if (it.category or "") not in ("food", "hotel", "transport", "transfer")
        and not str(it.item_id or "").startswith("leg-bridge-")
    ]
    # 注入的 must 落卡（add 前池被 avoid 挡了——静安寺只可能来自注入）
    assert any(n == "静安寺" for n, _d in seated_after), sorted(seated_after)
    # keep 钉设计：其余卡日不动（时刻由引擎重排——布局可更优，卡不换天）
    for name, day in seated_before:
        assert (name, day) in set(seated_after), (name, day, sorted(seated_after))


def test_edit_session_add_unknown_name_skeleton(monkeypatch):
    """R13-#2：add 池外名（「用户随便说的地方」）→ 骨架兜底——引擎照常
    服务（不 INFEASIBLE 不回落），B-01 不吞点：名字要么落卡要么留痕
    plan.unplaced / unarranged_musts。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import (
        edit_session_via_trip_solver,
        replan_session_via_trip_solver,
    )

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session = PlanSession(
        session_id="sess-add2",
        device_id="dadd2",
        cities=["上海"],
        days=2,
        start_date="2026-11-25",
        must_visits=["外滩", "豫园"],
        preferences="",
    )
    out = replan_session_via_trip_solver(session, store=_edit_store())
    assert out is not None and out.engine == "cpsat" and session.plan is not None
    new_plan, outcome = edit_session_via_trip_solver(
        session,
        store=_edit_store(),
        ops=[{"kind": "add", "name": "用户随便说的地方", "poi_id": None}],
    )
    assert new_plan is not None, "skeleton add must still serve via engine"
    card_names = {it.name for d in new_plan.days for it in d.items if it.name}
    unplaced_names = set(new_plan.unarranged_musts or []) | {
        u.name for u in new_plan.unplaced
    }
    assert "用户随便说的地方" in (card_names | unplaced_names), (
        sorted(card_names),
        sorted(unplaced_names),
    )


def test_generator_lands_intake_constraints_on_session(monkeypatch):
    """R13p：首屏引擎会话必须落地班次/分城/中途转移日——否则同会话发
    「重排」时 _session_snapshot 从会话读这些字段全空，约束静默丢失
    （legacy start_nlu.start 是全会存的；引擎缝此前只存到达/离开时刻）。"""
    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session, outcome = generate_session_via_trip_solver(
        device_id="t-r13p-constraints",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["外滩"],
        store=_store(),
        arrival_no="G123",
        departure_no="G456",
        intercity_mode="train",
        city_days={"上海": 1},
        arrival_date="2026-11-25",
        departure_date="2026-11-25",
    )
    assert outcome is not None and outcome.engine == "cpsat"
    assert session is not None
    assert session.arrival_no == "G123"
    assert session.departure_no == "G456"
    assert session.intercity_mode == "train"
    assert dict(session.city_days) == {"上海": 1}
    assert session.arrival_date == "2026-11-25"
    assert session.departure_date == "2026-11-25"


def test_session_snapshot_reads_intake_constraints():
    """R13p：重排快照必须从会话读回班次/分城/中途日/首日出发——
    intercity_mode 此前连 _session_snapshot 都没传（会话存了也白存）。"""
    from app.services.agent.plan import PlanSession
    from app.services.trip_solver.live import _session_snapshot

    session = PlanSession(
        session_id="ts-r13p-snap",
        device_id="t",
        cities=["上海"],
        days=3,
        start_date="2026-11-25",
        # 只给 intercity_mode、不给班次号：模式只能来自这个字段，
        # 才能验 _session_snapshot 真的把它传进快照（班次号会掩盖）
        intercity_mode="flight",
        city_days={"上海": 3},
        # 中途转移日：到达/离开都落在第 2 天（非端点，才会显式传日号）
        arrival_date="2026-11-26",
        departure_date="2026-11-26",
        comment_day_start="11:00",
    )
    snap = _session_snapshot(session, _store())
    assert snap is not None
    req = snap.request
    assert req.arrival_mode == "flight"
    assert req.departure_mode == "flight"
    assert req.day1_start == "11:00"
    assert dict(req.city_days) == {"上海": 3}
    assert req.arrival_day == 2
    assert req.departure_day == 2  # 中途转移日（非末日，显式传）


def test_generator_parses_day1_start_from_preferences(monkeypatch):
    """R13p：H5 把自由输入折进 preferences（brief 为空时形状闸放行），
    「leave hotel on 11am」必须被引擎读到并落地 comment_day_start——
    否则引擎首屏不认首日出发时刻（legacy start_nlu 会正则解析）。"""
    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    session, outcome = generate_session_via_trip_solver(
        device_id="t-r13p-daystart",
        cities=["上海"],
        days=1,
        start_date="2026-11-25",
        musts=["外滩"],
        store=_store(),
        preferences="leave hotel on 11am",
    )
    assert outcome is not None and outcome.engine == "cpsat"
    assert session is not None
    assert session.comment_day_start == "11:00"
