# -*- coding: utf-8 -*-
"""trip_items 数据库事实化（2026-11-13 用户拍板）：

「行程中心里的内容，行程号，行程内容，心愿单，已经安排，不要去，已经预定，
应该都是数据库的数据。当我删行程的时候，数据库里行程和行程关联的已安排就
变成无挂靠的心愿单了。」

锚点：
  * 行带设备归属——别的设备（冒烟/另一个浏览器）建行/翻牌不进我的看板；
  * 同名不跨设备去重；
  * 看板接口按 X-Device-ID 读写，越权 PATCH/DELETE 404；
  * 删行程 = 名下 scheduled 行在库里变回「无挂靠心愿单」。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.trip_items import get_trip_item_service, router
from app.services.trip_items import TripItemService


def make_app(service: TripItemService) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_trip_item_service] = lambda: service
    return app


def test_create_records_owner_and_board_is_device_scoped():
    svc = TripItemService()
    svc.create("外滩", source="chat", city="上海", owner_device_id="dev-a")
    svc.create("看熊猫", source="chat", city="成都", owner_device_id="dev-b")
    a = svc.list_groups(None, "dev-a")
    b = svc.list_groups(None, "dev-b")
    assert [r["name"] for r in a["wishlist"]] == ["外滩"]
    assert [r["name"] for r in b["wishlist"]] == ["看熊猫"]
    # 不带设备（脚本/运维）仍看全量
    assert len(svc.list_groups(None)["wishlist"]) == 2


def test_same_name_on_two_devices_is_two_rows():
    """冒烟设备建「外滩」不得并进用户的「外滩」。"""
    svc = TripItemService()
    mine = svc.create("外滩", source="chat", city="上海", owner_device_id="dev-a")
    other = svc.create("外滩", source="chat", city="上海", owner_device_id="dev-b")
    assert mine["id"] != other["id"]
    assert len(svc.list_groups(None)["wishlist"]) == 2


def test_api_create_and_list_are_device_scoped():
    svc = TripItemService()
    with TestClient(make_app(svc)) as client:
        r = client.post(
            "/api/v1/trip-items",
            json={"name": "豫园", "source": "chat", "city": "上海"},
            headers={"X-Device-ID": "dev-a"},
        )
        assert r.status_code == 201
        assert r.json()["owner_device_id"] == "dev-a"
        client.post(
            "/api/v1/trip-items",
            json={"name": "看熊猫", "source": "chat", "city": "成都"},
            headers={"X-Device-ID": "dev-b"},
        )
        mine = client.get("/api/v1/trip-items", headers={"X-Device-ID": "dev-a"}).json()
        assert [i["name"] for i in mine["wishlist"]] == ["豫园"]


def test_api_patch_other_device_row_is_404():
    svc = TripItemService()
    row = svc.create("豫园", source="chat", city="上海", owner_device_id="dev-a")
    with TestClient(make_app(svc)) as client:
        r = client.patch(
            f"/api/v1/trip-items/{row['id']}",
            json={"status": "scheduled", "day": 2},
            headers={"X-Device-ID": "dev-b"},
        )
        assert r.status_code == 404
        assert svc.get(row["id"])["status"] == "wishlist"


def test_delete_itinerary_releases_rows_to_unbound_wishlist():
    """删行程 → 名下 scheduled 行在库里变回无挂靠心愿单（day/itinerary 清空）。"""
    svc = TripItemService()
    row = svc.create(
        "陕西历史博物馆",
        source="chat",
        city="西安",
        itinerary_id="it-abc12345",
        owner_device_id="dev-a",
    )
    svc.update(row["id"], status="scheduled", day=3)
    released = svc.release_itinerary("it-abc12345")
    assert released
    got = svc.get(row["id"])
    assert got["status"] == "wishlist"
    assert not got.get("itinerary_id")
    assert got.get("day") is None
