# -*- coding: utf-8 -*-
"""R26 打车卡/晨卡按意图时刻落班次链（2026-11-23 用户令「酒店、打车、晚餐
的时间也应该同样能改」）。

链式口径（R15/R16，legs.attach_outbound_taxi_cards 同源派生）：
  打车卡/班次日晨卡时刻 = 班次 − 缓冲15 − 叫车15 − 车程（两卡同值）。
用户给意图时刻 T → 取班次表里链起点离 T 最近的班 → set_access_departure
整链重锚（chosen 落卡、晨卡随班次平移、后继按 retime 游标级联）。
"""

from __future__ import annotations

from datetime import time as dtime

import pytest
from fastapi.testclient import TestClient

from app.api.plan import get_plan_sessions
from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.itinerary import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from tests.test_plan_api import StubAdapter, make_app

HEADERS = {"X-Device-ID": "device-1"}
URL = "/api/v1/plan/s-chain/departure"


def _morning(start=7 * 60 + 45):
    return VisitItem(
        item_id="hotel-morning-d1",
        name="🏨 从酒店出发",
        category="hotel",
        city="北京",
        day=1,
        start_time=dtime(start // 60, start % 60),
        end_time=dtime(start // 60, start % 60),
        duration_minutes=0,
        soft_pin=True,
        anchor_location=GeoPoint(lon=116.4074, lat=39.9042),
    )


def _outbound(start=8 * 60 + 30, **extra):
    base = dict(
        item_id="access-out-mt",
        name="🚌 前往慕田峪长城",
        category="transfer",
        city="北京",
        day=1,
        start_time=dtime(start // 60, start % 60),
        end_time=dtime(10, 8),
        duration_minutes=98,
        synthetic=True,
        access_mode="shuttle",
        access_service_minutes=90,
        access_last_mile_minutes=8,
        access_taxi_minutes=15,
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_depart_first=7 * 60 + 30,
        access_depart_last=10 * 60 + 30,
        access_depart_times=["07:30", "08:30", "09:30", "10:30"],
    )
    base.update(extra)
    return VisitItem(**base)


def _site():
    return VisitItem(
        item_id="mt",
        name="慕田峪长城",
        category="sight",
        city="北京",
        day=1,
        start_time=dtime(10, 8),
        end_time=dtime(14, 8),
        duration_minutes=240,
        location=GeoPoint(lon=116.5598, lat=40.4267),
    )


def _night():
    # 真实盘必有夜卡：reanchor_hotel_cards 的孤儿晨卡清理要求「首日夜卡在」
    return VisitItem(
        item_id="hotel-night-d1",
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="北京",
        day=1,
        start_time=dtime(21, 0),
        end_time=dtime(21, 30),
        duration_minutes=30,
        soft_pin=True,
    )


def _session(items=None):
    agent = PlanningAgent(StubAdapter([]))
    app = make_app(agent)
    store = app.dependency_overrides[get_plan_sessions]()
    store.save(
        PlanSession(
            session_id="s-chain",
            device_id="device-1",
            state="ready",
            plan=ItineraryPlan(
                itinerary_id="it-chain",
                cities=["北京"],
                days=[
                    DayPlan(
                        day=1,
                        base_city="北京",
                        items=items
                        if items is not None
                        else [_morning(), _outbound(), _site(), _night()],
                    )
                ],
            ),
        )
    )
    return agent, app, store


def _start_min(item):
    return item.start_time.hour * 60 + item.start_time.minute


def test_chain_time_morning_snaps_to_nearest_departure():
    """意图 08:46 → 最近链起点 08:45（09:30 班）：去程卡 09:30，晨卡在场。"""
    agent, _app, store = _session()
    session = store.get("s-chain", device_id="device-1")
    _, summary, _notes = agent.set_chain_time(
        session, "hotel-morning-d1", depart=dtime(8, 46)
    )
    items = {i.item_id: i for i in session.plan.days[0].items}
    # 夹具没有 materialized 班次窗（access_depart_first/last 齐全时 pin 才生效），
    # 卡面时刻由游标重排；契约锚点是「点选值=最近链起点对应的班次」落卡。
    assert items["access-out-mt"].access_chosen_depart == "09:30"
    assert "hotel-morning-d1" in items
    assert "09:30" in str(summary.change_summary[0])


def test_chain_time_keeps_identity_taxi_gap():
    """打车卡路径（gap=45）：意图 07:50 → 最近链起点 07:45（08:30 班），班次不变。"""
    agent, _app, store = _session()
    session = store.get("s-chain", device_id="device-1")
    _, summary, _notes = agent.set_chain_time(
        session, "access-out-mt", depart=dtime(7, 50), taxi=True, chain_gap=45
    )
    items = {i.item_id: i for i in session.plan.days[0].items}
    assert items["access-out-mt"].access_chosen_depart == "08:30"
    assert "hotel-morning-d1" in items
    assert "打车" in str(summary.change_summary[0])


def test_chain_time_morning_no_shuttle_plain_retime():
    """城内日（无去程卡）晨卡：回落 plain retime（R21 出发点锚），起点=意图时刻。"""
    agent, _app, store = _session(items=[_morning(), _site(), _night()])
    session = store.get("s-chain", device_id="device-1")
    _, summary, _notes = agent.set_chain_time(
        session, "hotel-morning-d1", depart=dtime(9, 0)
    )
    items = {i.item_id: i for i in session.plan.days[0].items}
    assert _start_min(items["hotel-morning-d1"]) == 9 * 60
    assert "从酒店出发" in str(summary.change_summary[0])


def test_chain_time_no_timetable_raises():
    agent, _app, store = _session(
        items=[_morning(), _outbound(access_depart_times=[]), _night()]
    )
    session = store.get("s-chain", device_id="device-1")
    with pytest.raises(ValueError) as ctx:
        agent.set_chain_time(session, "hotel-morning-d1", depart=dtime(8, 46))
    assert str(ctx.value) == "no_timetable"


def test_chain_time_api_mode_leave_plumbs_through():
    """API mode=leave（城内日晨卡）：POST /departure 200，晨卡起点=意图时刻。"""
    _agent, app, _store = _session(items=[_morning(), _site(), _night()])
    with TestClient(app, headers=HEADERS) as client:
        r = client.post(
            URL,
            json={
                "item_id": "hotel-morning-d1",
                "direction": "out",
                "depart": "09:00",
                "mode": "leave",
            },
        )
        assert r.status_code == 200, r.text
        items = {i["item_id"]: i for i in r.json()["plan"]["days"][0]["items"]}
        assert items["hotel-morning-d1"]["start_time"].startswith("09:00")


def _engine_lunch():
    return VisitItem(
        item_id="meal-lunch-2",
        name="午餐",
        category="food",
        city="北京",
        day=1,
        start_time=dtime(12, 0),
        end_time=dtime(13, 0),
        duration_minutes=60,
        soft_pin=True,
    )


def _engine_lunch():
    return VisitItem(
        item_id="meal-lunch-2",
        name="午餐",
        category="food",
        city="北京",
        day=1,
        start_time=dtime(12, 0),
        end_time=dtime(13, 0),
        duration_minutes=60,
        soft_pin=True,
    )


def test_retime_accepts_meal_sibling_id():
    """R27：餐卡换族不再 404（meal-lunch-2 ↔ food-lunch-ph-d2）。"""
    agent, _app, store = _session(
        items=[_morning(), _engine_lunch(), _site(), _night()]
    )
    session = store.get("s-chain", device_id="device-1")
    _, summary, _notes = agent.retime_item(
        session, "food-lunch-ph-d2", start=dtime(12, 30)
    )
    items = {i.item_id: i for i in session.plan.days[0].items}
    card = items["meal-lunch-2"]
    # 验收契约：不 404、编辑被接受落盘（起点离开原 12:00）、摘要带所输时刻；
    # 餐槽/游标可能再微调落位，不锚死绝对时刻。
    assert "meal-lunch-2" in items
    assert _start_min(card) != 12 * 60
    assert "12:30" in str(summary.change_summary[0])


def _legacy_lunch():
    return VisitItem(
        item_id="food-lunch-ph-d2",
        name="午饭（自由安排）",
        category="food",
        city="北京",
        day=1,
        start_time=dtime(12, 0),
        end_time=dtime(13, 0),
        duration_minutes=60,
        soft_pin=True,
        anchor_location=GeoPoint(lon=116.40, lat=39.90),
    )


def test_retime_accepts_engine_id_for_legacy_card():
    """反向：legacy 家族卡用 engine id 点名同样解析。"""
    agent, _app, store = _session(
        items=[_morning(), _legacy_lunch(), _site(), _night()]
    )
    session = store.get("s-chain", device_id="device-1")
    _, summary, _notes = agent.retime_item(session, "meal-lunch-2", start=dtime(12, 30))
    items = {i.item_id: i for i in session.plan.days[0].items}
    card = items["food-lunch-ph-d2"]
    assert "food-lunch-ph-d2" in items
    assert _start_min(card) != 12 * 60
    assert "12:30" in str(summary.change_summary[0])
