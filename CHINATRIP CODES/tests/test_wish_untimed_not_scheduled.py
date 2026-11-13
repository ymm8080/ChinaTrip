# -*- coding: utf-8 -*-
"""2026-11-13 心愿打卡「未排却显示已排」回归锚。

事实（用户西安实测）：陕西历史博物馆挂在第 3 天 items 里但 start_time=None
（H5 渲染成「未排」），心愿单行却被翻成 scheduled + note「已安排：第3天」。
两个方向都锚死：无时刻卡不算已排；有时刻照常翻牌。
"""

from __future__ import annotations

from datetime import time as T

from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.trip_items import TripItemService
from tests.test_wish_bind import CountingLLM, PandaStore


def _agent(svc):
    return PlanningAgent(
        CountingLLM(),
        trip_items=svc,
        poi_details=PandaStore(),
        amap_client=None,
        auto_restaurants=False,
    )


def _museum(*, day=3, timed=False):
    return VisitItem(
        item_id="v-museum",
        name="陕西历史博物馆",
        city="西安",
        day=day,
        poi_id="m1_f1fd2d8d516e",
        duration_minutes=240,
        category="museum",
        pinned=True,
        must=True,
        start_time=T(12, 30) if timed else None,
        end_time=T(16, 30) if timed else None,
    )


def _session(plan):
    session = PlanSession(session_id="s-untimed", device_id="d1", cities=["西安"])
    session.plan = plan
    return session


def _plan(item):
    return ItineraryPlan(
        itinerary_id="it-untimed",
        cities=["西安"],
        days=[DayPlan(day=item.day, base_city="西安", items=[item])],
    )


def test_untimed_wish_row_stays_wishlist():
    """None-None 灰卡不得算已排期（否则看板/行程两处互相打脸）。"""
    svc = TripItemService()
    row = svc.create("陕西历史博物馆", source="chat", city="西安")
    agent = _agent(svc)
    agent._wish_bindings["陕西历史博物馆"] = {
        "name": "陕西历史博物馆",
        "city": "西安",
        "source_poi_id": "m1_f1fd2d8d516e",
        "location": None,
    }
    agent._sync_wish_rows(_session(_plan(_museum(timed=False))))
    agent._sync_planned_rows(_session(_plan(_museum(timed=False))))

    fresh = svc.get(row["id"])
    assert fresh["status"] == "wishlist"
    assert "已安排" not in str(fresh.get("note") or "")


def test_timed_wish_row_schedules():
    """反向锚：真落上时刻的心愿照常翻已排期（闸不许误伤）。"""
    svc = TripItemService()
    row = svc.create("陕西历史博物馆", source="chat", city="西安")
    agent = _agent(svc)
    agent._wish_bindings["陕西历史博物馆"] = {
        "name": "陕西历史博物馆",
        "city": "西安",
        "source_poi_id": "m1_f1fd2d8d516e",
        "location": None,
    }
    session = _session(_plan(_museum(timed=True)))
    agent._sync_wish_rows(session)
    agent._sync_planned_rows(session)

    fresh = svc.get(row["id"])
    assert fresh["status"] == "scheduled"
    assert fresh["day"] == 3
    assert "已安排" in str(fresh.get("note") or "")
