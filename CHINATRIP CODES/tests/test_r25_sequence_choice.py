# -*- coding: utf-8 -*-
"""R25 顺序选边（用户令：文本已按天写好 → 问保持顺序还是按天气/
地理重排）。keep=site_days 天钉喂引擎（C-25）与 legacy；replan=两边都不吃。
"""

from types import SimpleNamespace

from ortools.sat.python import cp_model
from test_brief_text_input import SitesStore

from app.api.plan import _plan_turn_body
from app.services.agent.plan import PlanSession
from app.services.trip_solver.live import _session_snapshot, snapshot_from_request
from app.services.trip_solver.model.c25_must_days import add_c25_must_days


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


def test_c25_forbids_wrong_day_presence():
    snapshot = SimpleNamespace(
        request=SimpleNamespace(
            days=3,
            musts=[SimpleNamespace(rid="r1", day_hint=2)],
        ),
        candidates=[SimpleNamespace(cid="c1", kind="requested", rid="r1")],
    )
    enriched = SimpleNamespace(snapshot=snapshot)

    m = cp_model.CpModel()
    presence = {("c1", d): m.NewBoolVar("p%d" % d) for d in (1, 2, 3)}
    bundle = SimpleNamespace(model=m, presence=presence, days=[1, 2, 3])
    add_c25_must_days(bundle, enriched)
    m.Add(presence[("c1", 1)] == 1)  # 错天在场 → 不可行
    assert cp_model.CpSolver().Solve(m) == cp_model.INFEASIBLE

    m2 = cp_model.CpModel()
    presence2 = {("c1", d): m2.NewBoolVar("q%d" % d) for d in (1, 2, 3)}
    bundle2 = SimpleNamespace(model=m2, presence=presence2, days=[1, 2, 3])
    add_c25_must_days(bundle2, enriched)
    m2.Add(presence2[("c1", 2)] == 1)  # 指定天在场 → 可行
    assert cp_model.CpSolver().Solve(m2) in (cp_model.FEASIBLE, cp_model.OPTIMAL)

    m3 = cp_model.CpModel()
    presence3 = {("c1", d): m3.NewBoolVar("s%d" % d) for d in (1, 2, 3)}
    bundle3 = SimpleNamespace(model=m3, presence=presence3, days=[1, 2, 3])
    add_c25_must_days(bundle3, enriched)
    m3.Add(presence3[("c1", 3)] == 1)  # 又一错天 → 不可行
    assert cp_model.CpSolver().Solve(m3) == cp_model.INFEASIBLE


def test_plan_turn_body_sequence_ask_filters_pending():
    s = _sess(
        state="site_confirm",
        pending_sites=["故宫博物院", "天坛"],
        site_days={"故宫博物院": 1, "天坛": 2, "颐和园": 3},
    )
    ask = _plan_turn_body(s, None, None).get("sequence_ask")
    assert ask and ask["days"] == {"故宫博物院": 1, "天坛": 2}
    assert ask["options"] == ["keep", "replan"]

    s2 = _sess(state="site_confirm", pending_sites=["天坛"])
    assert "sequence_ask" not in _plan_turn_body(s2, None, None)
