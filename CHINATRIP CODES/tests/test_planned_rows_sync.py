# -*- coding: utf-8 -*-
"""行程中心「已安排」分区补源回归锚（2026-11-12 用户报「已经安排的景点
没有移动到已安排的部分下，还在心愿单里」）：H5 已安排分区只渲染
trip_items 的 scheduled 行，而 scheduled 行此前只能由心愿行翻转产生——
非许愿的引擎排点永远不产生行，分区按构造恒空。修复 = _sync_planned_rows
（plan.py，跟随 _sync_wish_rows 五个收口点）：plan 里真实落排（有
poi_id，占位卡不算）的非餐/酒店参访 upsert 成 scheduled 行。
"""

from __future__ import annotations

import asyncio

from app.services.agent.plan import PlanningAgent
from app.services.itinerary import VisitItem
from app.services.itinerary.models import DayPlan, ItineraryPlan
from app.services.trip_items import TripItemService
from tests.test_wish_bind import CountingLLM, PandaStore, _visits


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


def _item(name, *, poi_id="POI1", cat="attraction", day=1):
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="成都",
        day=day,
        duration_minutes=120,
        category=cat,
        poi_id=poi_id,
    )


def _session(agent, plan):
    from app.services.agent.plan import PlanSession

    session = PlanSession(session_id="s1", device_id="d1", cities=["成都"])
    session.plan = plan
    return session


def test_planned_attraction_creates_scheduled_row():
    """非许愿的引擎排点（宽窄巷子式）：已安排分区此前按构造恒空——
    修复后 source=plan 的 scheduled 行落表。"""
    svc = TripItemService()
    agent = _agent(svc)
    plan = _plan_with([_item("宽窄巷子", poi_id="KZ01")])
    agent._sync_planned_rows(_session(agent, plan))
    rows = svc.list_groups("it-test")["scheduled"]
    assert len(rows) == 1
    assert rows[0]["name"] == "宽窄巷子"
    assert rows[0]["source"] == "plan"
    assert rows[0]["day"] == 1
    assert "已安排" in (rows[0].get("note") or "")


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


def test_stale_plan_row_removed_when_item_leaves_plan():
    """引擎把点移出 plan：本行程 source=plan 的滞留 scheduled 行删除——
    不留「已排期但实际没排」假卡。"""
    svc = TripItemService()
    agent = _agent(svc)
    session = _session(agent, _plan_with([_item("宽窄巷子", poi_id="KZ01")]))
    agent._sync_planned_rows(session)
    assert len(svc.list_groups("it-test")["scheduled"]) == 1
    # 模拟编辑删点：plan 不再含该点，再跑收口
    for day in session.plan.days:
        day.items = [
            i
            for i in day.items
            if not (isinstance(i, VisitItem) and i.poi_id == "KZ01")
        ]
    agent._sync_planned_rows(session)
    assert svc.list_groups("it-test")["scheduled"] == []


def test_start_end_to_end_scheduled_zone_filled(monkeypatch):
    """端到端：规划回合收口后已安排分区非空（真实 harness 双点布景）。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    svc = TripItemService()
    agent = _agent(svc)
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    scheduled = svc.list_groups(session.plan.itinerary_id)["scheduled"]
    planned_names = {v.name for v in _visits(session) if v.poi_id}
    row_names = {r["name"] for r in scheduled}
    assert planned_names <= row_names
