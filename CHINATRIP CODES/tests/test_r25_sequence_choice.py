# -*- coding: utf-8 -*-
"""R25 顺序选边（用户令：文本已按天写好 → 问保持顺序还是按天气/
地理重排）。keep=日内固定（同组同日+顺序固定）、整天可随天气换（C-25 块）；
replan=不建块约束、引擎自排。
"""

from types import SimpleNamespace

from ortools.sat.python import cp_model
from test_brief_text_input import SitesStore

from app.api.plan import _plan_turn_body
from app.services.agent.plan import PlanSession
from app.services.trip_solver.live import _session_snapshot, snapshot_from_request
from app.services.trip_solver.model.c25_must_days import (
    add_c25_day_blocks,
    day_hint_terms,
)


def _known(names, city="北京"):
    return {(city, n): {"name": n, "city": city, "category": "sight"} for n in names}


def _sess(**kw):
    base = dict(session_id="s1", device_id="d1", cities=["北京"], days=4)
    base.update(kw)
    return PlanSession(**base)


def test_snapshot_from_request_sets_day_hint():
    store = SitesStore(known=_known(["故宫博物院"]))
    snap = snapshot_from_request(
        cities=["北京"],
        days=4,
        start_date="2026-12-01",
        musts=["故宫博物院"],
        store=store,
        must_days={"故宫博物院": 2},
    )
    assert [m.day_hint for m in snap.request.musts] == [2]
    snap2 = snapshot_from_request(
        cities=["北京"],
        days=4,
        start_date="2026-12-01",
        musts=["故宫博物院"],
        store=store,
    )
    assert [m.day_hint for m in snap2.request.musts] == [None]


def test_session_snapshot_keep_vs_replan():
    store = SitesStore(known=_known(["故宫博物院"]))
    keep = _sess(
        sequence_choice="keep",
        site_days={"故宫博物院": 2},
        must_visits=["故宫博物院"],
    )
    assert [m.day_hint for m in _session_snapshot(keep, store).request.musts] == [2]
    both = _sess(
        sequence_choice="both",
        site_days={"故宫博物院": 2},
        must_visits=["故宫博物院"],
    )
    assert [m.day_hint for m in _session_snapshot(both, store).request.musts] == [2]
    replan = _sess(
        sequence_choice="replan",
        site_days={"故宫博物院": 2},
        must_visits=["故宫博物院"],
    )
    assert [m.day_hint for m in _session_snapshot(replan, store).request.musts] == [
        None
    ]
    legacy = _sess(
        site_days={"故宫博物院": 2},
        must_visits=["故宫博物院"],
    )
    # 旧口径（未选边）：引擎不吃天钉（legacy 自己吃 site_days）
    assert [m.day_hint for m in _session_snapshot(legacy, store).request.musts] == [
        None
    ]


def _block_world(hint=2, days=(1, 2, 3)):
    snapshot = SimpleNamespace(
        request=SimpleNamespace(
            days=3,
            musts=[
                SimpleNamespace(rid="r1", day_hint=hint),
                SimpleNamespace(rid="r2", day_hint=hint),
            ],
        ),
        candidates=[
            SimpleNamespace(cid="c1", kind="requested", rid="r1"),
            SimpleNamespace(cid="c2", kind="requested", rid="r2"),
        ],
    )
    enriched = SimpleNamespace(snapshot=snapshot)
    m = cp_model.CpModel()
    presence = {
        (c, d): m.NewBoolVar("p_%s_%d" % (c, d)) for c in ("c1", "c2") for d in days
    }
    start = {
        (c, d): m.NewIntVar(0, 1440, "s_%s_%d" % (c, d))
        for c in ("c1", "c2")
        for d in days
    }
    dur = {c: 60 for c in ("c1", "c2")}
    bundle = SimpleNamespace(
        model=m, presence=presence, start=start, dur=dur, days=list(days)
    )
    add_c25_day_blocks(bundle, enriched)
    return m, bundle, presence, start, dur


def test_c25_block_members_stay_same_day_but_may_swap():
    # 日内选择固定=同一块同一天：一个在第1天、一个在第2天 → 不可行
    m, bundle, presence, _start, _dur = _block_world()
    m.Add(presence[("c1", 1)] == 1)
    m.Add(presence[("c2", 2)] == 1)
    assert cp_model.CpSolver().Solve(m) == cp_model.INFEASIBLE

    # 整天可换：同一块一起落在第3天 → 可行
    m2, _b2, presence2, _s2, _d2 = _block_world()
    m2.Add(presence2[("c1", 3)] == 1)
    m2.Add(presence2[("c2", 3)] == 1)
    assert cp_model.CpSolver().Solve(m2) in (cp_model.FEASIBLE, cp_model.OPTIMAL)


def test_c25_block_order_chain_fixed():
    # 顺序固定：c2 排在 c1 之后（start2 >= start1+dur1）
    m, bundle, presence, start, dur = _block_world()
    m.Add(presence[("c1", 2)] == 1)
    m.Add(presence[("c2", 2)] == 1)
    m.Add(start[("c1", 2)] == 100)
    m.Add(start[("c2", 2)] == 120)  # < 100+60 → 违反顺序
    assert cp_model.CpSolver().Solve(m) == cp_model.INFEASIBLE
    m2, _b, presence2, start2, _d = _block_world()
    m2.Add(presence2[("c1", 2)] == 1)
    m2.Add(presence2[("c2", 2)] == 1)
    m2.Add(start2[("c1", 2)] == 100)
    m2.Add(start2[("c2", 2)] == 160)  # 刚好接上 → 可行
    assert cp_model.CpSolver().Solve(m2) in (cp_model.FEASIBLE, cp_model.OPTIMAL)


def test_day_hint_terms_prefer_written_day_but_never_block():
    m, bundle, presence, _start, _dur = _block_world()
    m.Add(presence[("c1", 2)] == 1)
    m.Add(presence[("c2", 2)] == 1)
    terms = day_hint_terms(bundle)
    assert terms  # 非空=_归日层真存在
    m.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(m) in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    assert solver.ObjectiveValue() == 0  # 落在写的天：零罚
    # 写的天装不下（天气/闭馆）→ 块换天，仍可行（软约束）
    m3, bundle3, presence3, _s3, _d3 = _block_world()
    m3.Add(presence3[("c1", 1)] == 1)
    m3.Add(presence3[("c2", 1)] == 1)
    m3.Minimize(sum(day_hint_terms(bundle3)))
    s3 = cp_model.CpSolver()
    assert s3.Solve(m3) in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    assert s3.ObjectiveValue() == 1  # 块换到非写明日：每块每天记 1


def test_plan_turn_body_sequence_ask_filters_pending():
    s = _sess(
        state="site_confirm",
        pending_sites=["故宫博物院", "天坛"],
        site_days={"故宫博物院": 1, "天坛": 2, "颐和园": 3},
    )
    ask = _plan_turn_body(s, None, None).get("sequence_ask")
    assert ask and ask["days"] == {"故宫博物院": 1, "天坛": 2}
    assert ask["options"] == ["keep", "replan", "both"]

    s2 = _sess(state="site_confirm", pending_sites=["天坛"])
    assert "sequence_ask" not in _plan_turn_body(s2, None, None)


def test_make_alt_engine_plan_builds_ready_alt_session(monkeypatch):
    """R25d both：引擎版会话独立生成（alt-*，replan 语义）并入库。"""
    import asyncio
    from types import SimpleNamespace

    import app.services.trip_solver.live as live_mod
    from app.api.plan import _make_alt_engine_plan

    fake_plan = SimpleNamespace(days=[], assumptions=["alt"], itinerary_id="it-alt")
    calls = {}

    def _fake_replan(session, **kwargs):
        calls["sequence_choice"] = session.sequence_choice
        calls["plan_is_none"] = session.plan is None
        return SimpleNamespace(plan=fake_plan)

    monkeypatch.setattr(live_mod, "replan_session_via_trip_solver", _fake_replan)

    from app.services.agent.plan import PlanSessionStore

    store = PlanSessionStore()
    sess = _sess(
        state="ready",
        must_visits=["故宫博物院"],
        site_days={"故宫博物院": 1},
        sequence_choice="keep",
    )
    store.save(sess)
    alt = asyncio.run(_make_alt_engine_plan(None, sess, store))
    assert alt is not None
    assert alt.session_id.startswith("alt-")
    assert alt.state == "ready"
    assert alt.sequence_choice == "replan"
    assert alt.plan is fake_plan
    assert calls["sequence_choice"] == "replan" and calls["plan_is_none"] is True
    assert store.get(alt.session_id, device_id=alt.device_id) is not None


def test_typed_sequence_choice_families():
    from app.services.trip_orchestrator.rounds import _typed_sequence_choice

    assert _typed_sequence_choice("按我写的顺序") == "keep"
    assert _typed_sequence_choice("keep my written order") == "keep"
    assert _typed_sequence_choice("按天气重排") == "replan"
    assert _typed_sequence_choice("replan by weather") == "replan"
    assert _typed_sequence_choice("两个都要") == "both"
    assert _typed_sequence_choice("Both please") == "both"
    # 点名站点/选站的句子不判顺序（不与站点解析抢）
    assert _typed_sequence_choice("必去：天坛，其余不去") is None
    assert _typed_sequence_choice("") is None


def test_typed_keep_lands_sequence_choice():
    # 打字回答落位口径（与 _answer_site_confirm 前半段同款）：
    # keep/replan 直落；both 消息轮建不了 alt → 按 keep 落。
    from app.services.trip_orchestrator.rounds import _typed_sequence_choice

    for text, want in (
        ("按我写的顺序", "keep"),
        ("按天气重排", "replan"),
        ("两个都要", "both"),
    ):
        probe = _sess(state="site_confirm", pending_sites=["故宫博物院"])
        typed = _typed_sequence_choice(text)
        probe.sequence_choice = typed
        assert probe.sequence_choice == want


def test_alt_plan_backlinks_to_primary():
    import asyncio
    from types import SimpleNamespace

    import app.services.trip_solver.live as live_mod
    from app.api.plan import _make_alt_engine_plan

    fake_plan = SimpleNamespace(days=[], assumptions=[], itinerary_id="it-x")
    monkey_target = live_mod.replan_session_via_trip_solver
    live_mod.replan_session_via_trip_solver = lambda session, **kw: SimpleNamespace(
        plan=fake_plan
    )
    try:
        from app.services.agent.plan import PlanSessionStore

        store = PlanSessionStore()
        primary = _sess(
            state="ready",
            must_visits=["故宫博物院"],
            site_days={"故宫博物院": 1},
            sequence_choice="keep",
        )
        store.save(primary)
        alt = asyncio.run(_make_alt_engine_plan(None, primary, store))
    finally:
        live_mod.replan_session_via_trip_solver = monkey_target
    assert alt is not None
    assert alt.alt_role == "engine"
    assert alt.alt_session_id == primary.session_id
    # 主会话回包带 role=primary
    body = _plan_turn_body(primary, None, None)
    primary.alt_session_id = alt.session_id
    body = _plan_turn_body(primary, None, None)
    assert body["alt_session_id"] == alt.session_id
    assert body["alt_role"] == "primary"
