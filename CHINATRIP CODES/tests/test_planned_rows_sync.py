# -*- coding: utf-8 -*-
"""行程中心「已安排」分区语义回归锚（2026-11-13 拍板：已排期只放已排的
心愿单）。

2026-11-12 首版把 plan 里真实落排的引擎点也 upsert 成 scheduled 行
（source=plan），用户没许愿过的景点因此出现在已排期——看板变成行程照抄。
本版收回补源：_sync_planned_rows 只翻既有用户心愿行；无行不建行；历史
source=plan 引擎行（scheduled/wishlist）一律清扫，booked/unwanted 例外。
"""

from __future__ import annotations

import asyncio
from datetime import time as clock_time

from app.services.agent.plan import PlanningAgent
from app.services.itinerary import VisitItem
from app.services.itinerary.models import DayPlan, ItineraryPlan
from app.services.trip_items import TripItemService
from tests.test_wish_bind import CountingLLM, PandaStore


def _agent(svc):
    return PlanningAgent(
        CountingLLM(), trip_items=svc, poi_details=PandaStore(), auto_restaurants=False
    )


def _plan_with(items):
    return ItineraryPlan(
        itinerary_id="it-test",
        cities=["成都"],
        days=[DayPlan(day=1, base_city="成都", items=items)],
    )


def _item(name, *, poi_id="POI1", cat="attraction", day=1, start="09:00"):
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="成都",
        day=day,
        duration_minutes=120,
        category=cat,
        poi_id=poi_id,
        # 2026-11-13「无时刻卡不算已排期」：排期行必须有落排时刻，夹具给默认值
        start_time=clock_time.fromisoformat(start),
    )


def _session(agent, plan):
    from app.services.agent.plan import PlanSession

    session = PlanSession(session_id="s1", device_id="d1", cities=["成都"])
    session.plan = plan
    return session


def _make_engine_row(svc, name, *, poi_id, status="scheduled"):
    row = svc.create(
        name, source="plan", itinerary_id="it-test", city="成都", poi_id=poi_id
    )
    if status == "scheduled":
        svc.update(row["id"], status=status, day=1)
    return svc.get(row["id"])


def test_engine_attraction_creates_no_scheduled_row():
    """非许愿的引擎排点（宽窄巷子式）：不建 source=plan 行——已排期只收
    心愿单里被排上的条目（2026-11-13 收回 11-12 的自动补源）。"""
    svc = TripItemService()
    agent = _agent(svc)
    plan = _plan_with([_item("宽窄巷子", poi_id="KZ01")])
    agent._sync_planned_rows(_session(agent, plan))
    assert svc.list_groups("it-test")["scheduled"] == []
    assert svc.list_groups("it-test")["wishlist"] == []


def test_planned_wish_row_flips_out_of_wishlist():
    """心愿行（看熊猫）被排上（基地正主）：从心愿单翻进已安排——
    用户报障的「还在心愿单里」核心场景（_name_dup 核名命中）。"""
    svc = TripItemService()
    svc.create("看熊猫", source="chat", city="成都")
    agent = _agent(svc)
    plan = _plan_with([_item("成都大熊猫繁育研究基地", poi_id="PANDA01")])
    agent._sync_planned_rows(_session(agent, plan))
    groups = svc.list_groups("it-test")
    assert not any(r["name"] == "看熊猫" for r in groups["wishlist"])
    row = next(r for r in groups["scheduled"] if r["name"] == "看熊猫")
    assert row["day"] == 1
    assert row["source"] == "chat"


def test_placeholder_and_food_cards_stay_out():
    """占位卡（无 poi_id）与餐卡不进已安排（与 _sync_wish_rows 同口径）。"""
    svc = TripItemService()
    agent = _agent(svc)
    plan = _plan_with(
        [
            VisitItem(
                item_id="v-ph",
                name="无名占位点",
                city="成都",
                day=1,
                duration_minutes=60,
                category="attraction",
                poi_id=None,
            ),
            _item("午餐占位", poi_id="F1", cat="food"),
        ]
    )
    agent._sync_planned_rows(_session(agent, plan))
    assert svc.list_groups("it-test")["scheduled"] == []


def test_unwanted_row_not_resurrected():
    """用户表态「不想去」的行：引擎排上也不翻牌（unwanted 优先）。"""
    svc = TripItemService()
    svc.create("宽窄巷子", source="chat", city="成都")
    row = svc.get(next(iter(svc._items)))
    svc.update(row["id"], status="unwanted")
    agent = _agent(svc)
    plan = _plan_with([_item("宽窄巷子", poi_id="KZ01")])
    agent._sync_planned_rows(_session(agent, plan))
    # 行无行程归属（itinerary_id=None），按全局组验证状态不被翻牌
    groups = svc.list_groups()
    assert any(r["name"] == "宽窄巷子" for r in groups["unwanted"])
    assert not any(r["name"] == "宽窄巷子" for r in groups["scheduled"])


def test_engine_scheduled_row_removed_even_when_point_still_planned():
    """历史 source=plan 补源行：点仍在 plan 也不得留在已排期（引擎行不是
    用户心愿）。"""
    svc = TripItemService()
    engine = _make_engine_row(svc, "宽窄巷子", poi_id="KZ01")
    agent = _agent(svc)
    plan = _plan_with([_item("宽窄巷子", poi_id="KZ01")])
    agent._sync_planned_rows(_session(agent, plan))
    assert svc.get(engine["id"]) is None
    assert svc.list_groups("it-test")["scheduled"] == []


def test_engine_scheduled_row_removed_when_item_leaves_plan():
    """点被移出 plan：source=plan 滞留 scheduled 行同样清扫——不留
    「已排期但实际没排」假卡。"""
    svc = TripItemService()
    engine = _make_engine_row(svc, "宽窄巷子", poi_id="KZ01")
    agent = _agent(svc)
    session = _session(agent, _plan_with([_item("人民公园", poi_id="RM01")]))
    agent._sync_planned_rows(session)
    assert svc.get(engine["id"]) is None
    assert svc.list_groups("it-test")["scheduled"] == []


def test_start_end_to_end_scheduled_zone_stays_empty_without_wishes(monkeypatch):
    """端到端：没有任何心愿单条目时，规划回合收口后已排期分区为空——
    引擎排点不再自动灌入。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    svc = TripItemService()
    agent = _agent(svc)
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    scheduled = svc.list_groups(session.plan.itinerary_id)["scheduled"]
    assert scheduled == []


def test_empty_wishes_still_flip_existing_wish_rows():
    """2026-11-12 二拍（排上了还在心愿单根因二）：「把X排进行程」类 diff
    回合 wishes 恒空——空愿望也必须跑 _sync_*，既有心愿行照样翻进已安排；
    无许愿的引擎点（宽窄巷子）不得补源成行。"""
    svc = TripItemService()
    svc.create("看熊猫", source="chat", city="成都")
    agent = _agent(svc)
    # 模拟会话既有绑定（聊天建行轮留下）：_sync_wish_rows 只认绑定名
    agent._wish_bindings["看熊猫"] = {
        "name": "成都大熊猫繁育研究基地",
        "city": "成都",
        "source_poi_id": "PANDA01",
        "location": {"lon": 104.1, "lat": 30.7},
    }
    session = _session(
        agent,
        _plan_with(
            [
                _item("成都大熊猫繁育研究基地", poi_id="PANDA01"),
                _item("宽窄巷子", poi_id="KZ01"),
            ]
        ),
    )
    notes, unresolved = asyncio.run(
        agent.sync_wishes_to_trip_items(session, [], user_texts=None)
    )
    assert notes == [] and unresolved == []
    groups = svc.list_groups("it-test")
    assert not any(r["name"] == "看熊猫" for r in groups["wishlist"])
    assert any(r["name"] == "看熊猫" for r in groups["scheduled"])
    # 已排期只放心愿单：无许愿的引擎排点不得现形
    assert not any(r["name"] == "宽窄巷子" for r in groups["scheduled"])
    assert all(r["source"] != "plan" for r in groups["scheduled"])


def test_user_wish_flip_failure_leaves_row_in_wishlist(monkeypatch):
    """翻牌失败 best-effort：用户心愿行留在心愿单，不炸收口、不产生
    引擎行残渣。"""
    svc = TripItemService()
    wish = svc.create("看熊猫", source="chat", city="成都")
    agent = _agent(svc)

    def _boom(*args, **kwargs):
        raise RuntimeError("pg down")

    monkeypatch.setattr(svc, "update", _boom)
    session = _session(agent, _plan_with([_item("看熊猫", poi_id="PANDA01")]))
    agent._sync_planned_rows(session)
    groups = svc.list_groups("it-test")
    assert any(r["id"] == wish["id"] for r in groups["wishlist"])
    assert groups["scheduled"] == []


def test_engine_rows_stuck_in_wishlist_swept():
    """旧码遗留的 source=plan 滞留心愿单行：不论点是否仍在 plan 一律清扫，
    不得以「来自行程」卡在心愿单。"""
    svc = TripItemService()
    svc.create(
        "长安十二时辰主题街区", source="plan", itinerary_id="it-test", city="成都"
    )
    agent = _agent(svc)
    session = _session(agent, _plan_with([_item("宽窄巷子", poi_id="KZ01")]))
    agent._sync_planned_rows(session)
    groups = svc.list_groups("it-test")
    assert not any(r["source"] == "plan" for r in groups["wishlist"])
    assert groups["scheduled"] == []

    # 点仍在 plan 的旧残渣行：同样清扫（不翻牌进已排期）
    svc2 = TripItemService()
    stuck = svc2.create(
        "西安钟楼", source="plan", itinerary_id="it-test", city="成都", poi_id="BELL01"
    )
    agent2 = _agent(svc2)
    session2 = _session(agent2, _plan_with([_item("西安钟楼", poi_id="BELL01")]))
    agent2._sync_planned_rows(session2)
    assert svc2.get(stuck["id"]) is None
    assert svc2.list_groups("it-test")["scheduled"] == []


def test_scheduled_row_bound_to_trip_but_point_left_plan_reverts():
    """2026-11-13 用户报「已排期里都是上海行程，可是行程根本没有上海」：
    挂在本行程上的排期行，点被换城/重排删掉之后必须回心愿单——已排期不
    得留「实际没排」的假卡（booked/unwanted 与别的行程的行不动）。"""
    svc = TripItemService()
    row = svc.create("外滩", source="chat", city="成都", itinerary_id="it-test")
    note = "来自聊天｜已安排：外滩（第1天 09:00）"
    svc.update(row["id"], status="scheduled", day=1, note=note)
    assert svc.list_groups("it-test")["scheduled"]
    agent = _agent(svc)
    session = _session(agent, _plan_with([_item("人民公园", poi_id="RM01")]))
    agent._sync_planned_rows(session)
    groups = svc.list_groups("it-test")
    assert not any(r["name"] == "外滩" for r in groups["scheduled"])
    got = next(r for r in groups["wishlist"] if r["name"] == "外滩")
    assert got["status"] == "wishlist"
    assert "已安排" not in (got.get("note") or "")


def test_revert_skips_rows_of_other_itineraries():
    """别的行程（it-other）的排期行不归本行程管——读侧对账不得越权。"""
    svc = TripItemService()
    row = svc.create("外滩", source="chat", city="成都", itinerary_id="it-other")
    svc.update(row["id"], status="scheduled", day=2)
    agent = _agent(svc)
    plan = _plan_with([_item("人民公园", poi_id="RM01")])
    agent._sync_planned_rows(_session(agent, plan))
    groups = svc.list_groups("it-other")
    assert any(r["name"] == "外滩" for r in groups["scheduled"])


def test_sync_trip_rows_flips_without_any_wish_names():
    """开档/保存对账入口（sync_trip_rows）：会话没有 must_visits / wish_bindings
    （✏️ 打开已存行程）时，行程里已落排的心愿行照样翻进已排期——用户报
    「陕历博在行程里被安排，却没从心愿单翻到已排期」的核心场景。"""
    svc = TripItemService()
    svc.create("陕西历史博物馆", source="chat", city="成都")
    agent = _agent(svc)
    session = _session(
        agent, _plan_with([_item("陕西历史博物馆", poi_id="M1", start="12:35")])
    )
    assert session.must_visits == [] and session.wish_bindings == {}
    agent.sync_trip_rows(session)
    groups = svc.list_groups("it-test")
    assert not any(r["name"] == "陕西历史博物馆" for r in groups["wishlist"])
    row = next(r for r in groups["scheduled"] if r["name"] == "陕西历史博物馆")
    assert row["day"] == 1


def test_route_endpoint_city_wish_not_absorbed():
    """2026-11-13 用户报「已排期里都是上海行程，可是行程根本没有上海」：
    cities 只是路线端点（上海→西安→上海 全程住西安）——行程里一天上海都
    没有，上海心愿不得被换绑/翻牌进本行程（城闸看逐日落点城）。"""
    from app.services.agent.plan import PlanSession

    svc = TripItemService()
    row = svc.create("外滩", source="chat", city="上海")
    agent = _agent(svc)
    agent._wish_bindings["外滩"] = {
        "name": "外滩",
        "city": "上海",
        "source_poi_id": "BUND",
    }
    plan = ItineraryPlan(
        itinerary_id="it-test",
        cities=["上海", "成都", "上海"],
        days=[
            DayPlan(
                day=1, base_city="成都", items=[_item("人民公园", poi_id="RM01")]
            )
        ],
    )
    session = PlanSession(
        session_id="s1", device_id="d1", cities=["上海", "成都", "上海"]
    )
    session.plan = plan
    agent._sync_wish_rows(session)
    got = svc.get(row["id"])
    assert got["status"] == "wishlist"
    assert not got.get("itinerary_id")


def test_trip_brief_is_not_a_wish():
    """2026-11-13 用户拍板「去成都玩三天不能算心愿单」：心愿单是某城市里
    具体可落地的活动/地址；「去X玩N天」是整趟行程简报，不建行。"""
    from app.services.agent.plan import _is_trip_brief_wish

    assert _is_trip_brief_wish("去成都玩3天")
    assert _is_trip_brief_wish("去成都玩三天")
    # 具体点位照常
    assert not _is_trip_brief_wish("宽窄巷子")
    assert not _is_trip_brief_wish("成都")


def test_trip_brief_creates_no_wish_row():
    import asyncio

    svc = TripItemService()
    agent = _agent(svc)
    session = _session(agent, _plan_with([_item("宽窄巷子", poi_id="KZ01")]))
    notes, unresolved = asyncio.run(
        agent.sync_wishes_to_trip_items(session, ["去成都玩3天"], user_texts=None)
    )
    assert notes == [] and unresolved == []
    assert svc.list_groups(None, "d1")["wishlist"] == []
