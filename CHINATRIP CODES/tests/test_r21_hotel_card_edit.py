"""R21 酒店卡编辑面（2026-11-23 用户拍板「酒店卡也要像景点卡一样，时间，
名字都可以编辑」「WE ONLY ALLOW USER TO INPUT HOTEL NAME AND ADDRESS」）：

① /items/{id}/set-hotel 地址直输——name 省略=只写地址（免验证），名称/
   坐标/身份不动，地址按住宿段铺开（占位卡继承、别家酒店绝不覆盖）；
② 名称与地址都为空 → 422 empty_request；
③ /items/{id}/retime 对酒店卡可用（用户权威）——夜卡只移卡本身（白天
   景点时刻绝不被重排），晨卡=出发点锚（当天其余非钉住景点围绕新离店
   时刻按序重排）；reanchor keep_ids 保护本回合目标卡。

「（城市）住 N 晚（MM-DD → MM-DD）」注释是前端 hotelStayLabel 的系统
派生文本：不落库、无端点可改（set-hotel 只收 name/address 两个输入面）。
"""

from datetime import time as dtime

from fastapi.testclient import TestClient
from test_plan_api import DEVICE_HEADERS, StubAdapter, make_app  # noqa: E402

from app.api.amap import get_search_chain
from app.api.plan import get_plan_sessions, get_settings
from app.config import Settings
from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.itinerary import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

NIGHT = "hotel-night-d1"
MORNING = "hotel-morning-d2"


def _hotel_app():
    agent = PlanningAgent(StubAdapter([]))
    app = make_app(agent)
    app.dependency_overrides[get_settings] = lambda: Settings(
        llm_backend="mock", amap_api_key="k", map_provider="amap"
    )
    app.dependency_overrides[get_search_chain] = lambda: []
    return app


def _plan_session(*, morning_verified_other: bool = False):
    night = VisitItem(
        item_id=NIGHT,
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="杭州",
        day=1,
        start_time=dtime(20, 0),
        end_time=dtime(21, 0),
        duration_minutes=60,
        soft_pin=True,
    )
    morning_kwargs = {}
    if morning_verified_other:
        morning_kwargs = dict(
            poi_id="B999",
            address="乙路2号",
            location=GeoPoint(lon=120.11, lat=30.25),
        )
    morning = VisitItem(
        item_id=MORNING,
        name="🏨 从酒店出发（今日起点）",
        category="hotel",
        city="杭州",
        day=2,
        start_time=dtime(8, 0),
        end_time=dtime(8, 30),
        duration_minutes=30,
        soft_pin=True,
        **morning_kwargs,
    )
    sight1 = VisitItem(
        item_id="v1",
        name="西湖",
        category="sight",
        city="杭州",
        day=1,
        start_time=dtime(13, 0),
        end_time=dtime(14, 15),
        duration_minutes=75,
    )
    sight2 = VisitItem(
        item_id="v2",
        name="灵隐寺",
        category="sight",
        city="杭州",
        day=2,
        start_time=dtime(9, 0),
        end_time=dtime(11, 0),
        duration_minutes=120,
    )
    return PlanSession(
        session_id="s-r21",
        device_id="device-1",
        state="ready",
        plan=ItineraryPlan(
            itinerary_id="it-r21",
            cities=["杭州"],
            days=[
                DayPlan(day=1, base_city="杭州", items=[sight1, night]),
                DayPlan(day=2, base_city="杭州", items=[morning, sight2]),
            ],
        ),
    )


def _items_by_id(body):
    return {i.get("item_id"): i for d in body["plan"]["days"] for i in d["items"]}


def _save(app, session):
    store = app.dependency_overrides[get_plan_sessions]()
    store.save(session)
    return store


def test_set_hotel_address_only_writes_stay_pair():
    app = _hotel_app()
    with TestClient(app) as client:
        _save(app, _plan_session())
        resp = client.post(
            "/api/v1/plan/s-r21/items/hotel-night-d1/set-hotel",
            json={"address": "龙井路1号"},
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        items = _items_by_id(resp.json())
        night = items[NIGHT]
        assert night["address"] == "龙井路1号"
        # 名称/身份不动（「回酒店·夜间休息」是系统占位注释，不可编辑）
        assert night["name"] == "🏨 回酒店·夜间休息"
        assert night["poi_id"] is None
        assert night["location"] is None
        # 住宿段铺开：占位晨卡继承地址，占位名不变
        morning = items[MORNING]
        assert morning["address"] == "龙井路1号"
        assert morning["name"] == "🏨 从酒店出发（今日起点）"


def test_set_hotel_address_only_skips_other_hotel():
    app = _hotel_app()
    with TestClient(app) as client:
        _save(app, _plan_session(morning_verified_other=True))
        resp = client.post(
            "/api/v1/plan/s-r21/items/hotel-night-d1/set-hotel",
            json={"address": "龙井路1号"},
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        items = _items_by_id(resp.json())
        # 晨卡已验证别家酒店：地址绝不被覆盖
        assert items[MORNING]["address"] == "乙路2号"
        assert items[NIGHT]["address"] == "龙井路1号"


def test_set_hotel_empty_request_is_422():
    app = _hotel_app()
    with TestClient(app) as client:
        _save(app, _plan_session())
        resp = client.post(
            "/api/v1/plan/s-r21/items/hotel-night-d1/set-hotel",
            json={},
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "empty_request"
        resp = client.post(
            "/api/v1/plan/s-r21/items/hotel-night-d1/set-hotel",
            json={"name": "   "},
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "empty_request"


def test_set_hotel_name_with_coords_still_writes_pair():
    app = _hotel_app()
    with TestClient(app) as client:
        _save(app, _plan_session())
        resp = client.post(
            "/api/v1/plan/s-r21/items/hotel-night-d1/set-hotel",
            json={
                "name": "酒店甲",
                "source_poi_id": "B0X",
                "address": "甲路1号",
                "lon": 120.1,
                "lat": 30.2,
            },
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        items = _items_by_id(resp.json())
        assert items[NIGHT]["name"] == "酒店甲"
        assert items[NIGHT]["address"] == "甲路1号"
        assert items[MORNING]["name"] == "🏨 从酒店出发（酒店甲）"
        assert items[MORNING]["address"] == "甲路1号"


def test_retime_hotel_night_card_moves_card_only():
    """夜卡改时=用户权威，但白天景点时刻绝不重排（R21 分支的核心回归）。"""
    app = _hotel_app()
    with TestClient(app) as client:
        _save(app, _plan_session())
        resp = client.post(
            "/api/v1/plan/s-r21/items/hotel-night-d1/retime",
            json={"start_time": "19:30"},
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        items = _items_by_id(resp.json())
        assert items[NIGHT]["start_time"] == "19:30:00"
        assert items[NIGHT]["name"] == "🏨 回酒店·夜间休息"
        # 关键：夜卡改时不得把白天景点拽去日始重游标
        assert items["v1"]["start_time"] == "13:00:00"


def test_retime_hotel_morning_card_anchors_day():
    """晨卡=当天出发点：改它后当天其余非钉住景点围绕新离店时刻按序重排。"""
    app = _hotel_app()
    with TestClient(app) as client:
        _save(app, _plan_session())
        resp = client.post(
            "/api/v1/plan/s-r21/items/hotel-morning-d2/retime",
            json={"start_time": "10:00"},
            headers=DEVICE_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        items = _items_by_id(resp.json())
        assert items[MORNING]["start_time"] == "10:00:00"
        # 景卡仍有时刻（围绕 10:00 离店重排，不会早于离店时刻）
        v2 = items["v2"]
        assert v2["start_time"] is not None
        assert v2["start_time"] >= "10:00"
