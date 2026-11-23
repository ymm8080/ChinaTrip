# -*- coding: utf-8 -*-
"""R20 桥卡出发时刻编辑（2026-11-23 用户令「乘车去下一站的时间应该也可
以编辑」）。

leg-bridge-* 桥卡只活在响应副本：桥卡的出发时刻=上一站的结束时刻。
POST /departure {item_id: leg-bridge-*, direction: "out", depart} 在响应
同形状探针盘面上解析桥卡→上一站（bridges.resolve_bridge_prev），然后：
普通站走 set_item_duration（开始保留、时长伸缩）；时长锁定骨架卡（占位
餐）走 retime 平移。用户可见不变量：
1. 编辑后响应里桥卡的开始时刻==所选时刻；
2. 下一站只在真被压住时才顺延（空隙原位不动）；
3. 盘面已变（桥卡 id 过期）→ 404 item_not_found，不静默吞。
"""

from __future__ import annotations

from datetime import time as dtime

from fastapi.testclient import TestClient

from app.api.plan import get_plan_sessions
from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.itinerary import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from tests.test_plan_api import StubAdapter, make_app

HEADERS = {"X-Device-ID": "device-1"}
URL = "/api/v1/plan/s-bridge/departure"


def _sight(item_id, name, start, end, lon=116.40, lat=39.90):
    return VisitItem(
        item_id=item_id,
        name=name,
        category="sight",
        city="北京",
        day=1,
        start_time=dtime(start // 60, start % 60),
        end_time=dtime(end // 60, end % 60),
        duration_minutes=end - start,
        location=GeoPoint(lon=lon, lat=lat),
    )


def _bridge_app(items):
    agent = PlanningAgent(StubAdapter([]))
    app = make_app(agent)
    store = app.dependency_overrides[get_plan_sessions]()
    store.save(
        PlanSession(
            session_id="s-bridge",
            device_id="device-1",
            state="ready",
            plan=ItineraryPlan(
                itinerary_id="it-bridge",
                cities=["北京"],
                days=[DayPlan(day=1, base_city="北京", items=items)],
            ),
        )
    )
    return app


def _two_sights():
    # 恰一张桥卡 leg-bridge-d1-1（空档 12:00→14:00；夜卡缺席所以无第二桥）
    return [
        _sight("a", "故宫", 10 * 60, 12 * 60),
        _sight("b", "天坛", 14 * 60, 16 * 60),
    ]


def _items_by_id(body):
    return {i["item_id"]: i for i in body["plan"]["days"][0]["items"]}


def test_bridge_departure_extends_prev_stop():
    """点 13:00 出发（晚于上一站结束）：上一站延长到 13:00 结束，下一站空隙原位不动。"""
    app = _bridge_app(_two_sights())
    with TestClient(app, headers=HEADERS) as client:
        r = client.post(
            URL,
            json={"item_id": "leg-bridge-d1-1", "direction": "out", "depart": "13:00"},
        )
        assert r.status_code == 200, r.text
        items = _items_by_id(r.json())
        card = items["a"]
        assert card["start_time"].startswith("10:00")
        assert card["end_time"].startswith("13:00")
        assert card["duration_minutes"] == 180
        assert items["b"]["start_time"].startswith("14:00")
        bridge = items["leg-bridge-d1-1"]
        assert bridge["start_time"].startswith("13:00")


def test_bridge_departure_shrinks_prev_stop():
    """点 11:00 出发（早于上一站结束）：上一站缩短，结束=11:00，下一站不动。"""
    app = _bridge_app(_two_sights())
    with TestClient(app, headers=HEADERS) as client:
        r = client.post(
            URL,
            json={"item_id": "leg-bridge-d1-1", "direction": "out", "depart": "11:00"},
        )
        assert r.status_code == 200, r.text
        items = _items_by_id(r.json())
        card = items["a"]
        assert card["start_time"].startswith("10:00")
        assert card["end_time"].startswith("11:00")
        assert card["duration_minutes"] == 60
        assert items["b"]["start_time"].startswith("14:00")
        assert items["leg-bridge-d1-1"]["start_time"].startswith("11:00")


def test_bridge_departure_idempotent_same_depart():
    """同一时刻重复提交：第二次同样成功（时长=开始到所选时刻，幂等）。"""
    app = _bridge_app(_two_sights())
    with TestClient(app, headers=HEADERS) as client:
        for _ in range(2):
            r = client.post(
                URL,
                json={
                    "item_id": "leg-bridge-d1-1",
                    "direction": "out",
                    "depart": "13:00",
                },
            )
            assert r.status_code == 200, r.text
        items = _items_by_id(r.json())
        assert items["a"]["end_time"].startswith("13:00")


def test_bridge_departure_placeholder_prev_retimes():
    """上一站是占位餐卡（时长锁定骨架）：平移餐卡使结束=所选时刻，下一站顺延。"""
    lunch = VisitItem(
        item_id="food-lunch-ph-d1",
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
    app = _bridge_app([lunch, _sight("b", "天坛", 15 * 60, 16 * 60)])
    with TestClient(app, headers=HEADERS) as client:
        r = client.post(
            URL,
            json={"item_id": "leg-bridge-d1-1", "direction": "out", "depart": "14:00"},
        )
        assert r.status_code == 200, r.text
        items = _items_by_id(r.json())
        meal = items["food-lunch-ph-d1"]
        assert meal["start_time"].startswith("13:00")
        assert meal["end_time"].startswith("14:00")
        assert items["b"]["start_time"] >= meal["end_time"]
        bridge = items.get("leg-bridge-d1-1")
        assert bridge is not None
        assert bridge["start_time"].startswith("14:00")


def test_bridge_departure_too_early_422():
    """所选时刻距上一站开始不足 15 分钟：422 bridge_depart_too_early。"""
    app = _bridge_app(_two_sights())
    with TestClient(app, headers=HEADERS) as client:
        r = client.post(
            URL,
            json={"item_id": "leg-bridge-d1-1", "direction": "out", "depart": "10:05"},
        )
        assert r.status_code == 422
        assert r.json()["detail"] == "bridge_depart_too_early"


def test_bridge_departure_unknown_id_404():
    """桥卡 id 对不上当前盘面（盘面已变/过期）：404 item_not_found，不静默吞。"""
    app = _bridge_app(_two_sights())
    with TestClient(app, headers=HEADERS) as client:
        r = client.post(
            URL,
            json={"item_id": "leg-bridge-d1-9", "direction": "out", "depart": "13:00"},
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "item_not_found"


def test_bridge_departure_prefers_host_over_nested_meal():
    """嵌套占位餐卡与宿主同尾（宿主 10:00-13:00、午饭 12:00-13:00）：桥卡
    13:00 出发的「上一站」必须是宿主卡——同刻提交零漂移，绝不抓占位餐卡
    平移、更不能把宿主/下一站搬去天板（R20 探针实录）。"""
    host = _sight("a", "故宫", 10 * 60, 13 * 60)
    host.duration_minutes = 180
    lunch = VisitItem(
        item_id="food-lunch-ph-d1",
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
    app = _bridge_app([host, lunch, _sight("b", "天坛", 14 * 60, 16 * 60)])
    with TestClient(app, headers=HEADERS) as client:
        r = client.post(
            URL,
            json={"item_id": "leg-bridge-d1-1", "direction": "out", "depart": "13:00"},
        )
        assert r.status_code == 200, r.text
        items = _items_by_id(r.json())
        assert items["a"]["start_time"].startswith("10:00")
        assert items["a"]["end_time"].startswith("13:00")
        assert items["food-lunch-ph-d1"]["start_time"].startswith("12:00")
        assert items["food-lunch-ph-d1"]["end_time"].startswith("13:00")
        assert items["b"]["start_time"].startswith("14:00")
        assert items["leg-bridge-d1-1"]["start_time"].startswith("13:00")


def test_bridge_departure_return_direction_422():
    """桥卡没有返向语义：direction=return → 422 bad_direction。"""
    app = _bridge_app(_two_sights())
    with TestClient(app, headers=HEADERS) as client:
        r = client.post(
            URL,
            json={
                "item_id": "leg-bridge-d1-1",
                "direction": "return",
                "depart": "13:00",
            },
        )
        assert r.status_code == 422
        assert r.json()["detail"] == "bad_direction"
