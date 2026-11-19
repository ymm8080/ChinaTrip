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
    # keep 钉设计：其余卡日不动（时刻由引擎重排——全局重排语义，布局
    # 可更优，卡不换天不消失）
    for name, day, st in before:
        if name == moved_name:
            continue
        assert (name, day) in after, (name, day, after)


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
