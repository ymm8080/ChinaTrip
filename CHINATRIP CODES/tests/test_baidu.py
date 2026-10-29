"""BaiduClient 测试：参数构造、坐标边界换算、形状对齐、异常映射。

全部走 httpx.MockTransport，不联网。fixture 坐标系均按百度真实行为
（BD-09 收发）；断言换算用往返容差而非硬编码绝对值。
"""

import asyncio

import httpx
import pytest

from app.services.amap_client import (
    AmapError,
    AmapQuotaExhaustedError,
    AmapTimeoutError,
)
from app.services.baidu_client import BaiduClient
from app.services.coords import bd09_to_gcj02, gcj02_to_bd09

AK = "test-ak"
BASE_URL = "https://api.map.baidu.com"


def make_client(handler) -> BaiduClient:
    return BaiduClient(
        ak=AK,
        base_url=BASE_URL,
        timeout_seconds=1.0,
        transport=httpx.MockTransport(handler),
    )


def ok_handler(body: dict):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=body)

    return handler, captured


def bd(lat: float, lng: float) -> dict:
    return {"lat": lat, "lng": lng}


# ---------- place/v2/search ----------


def test_search_poi_params_and_normalization():
    handler, captured = ok_handler(
        {
            "status": 0,
            "results": [
                {
                    "name": "故宫博物院",
                    "location": bd(39.918058, 116.411354),  # BD-09
                    "address": "北京市东城区景山前街4号",
                    "province": "北京市",
                    "city": "北京市",
                    "area": "东城区",
                    "uid": "e491ee79f4805b5d4355c2f7",
                    "telephone": "(010)85007008",
                    "detail_info": {
                        "tag": "旅游景点",
                        "overall_rating": "4.8",
                        "opening_hours": "08:30-17:00",
                    },
                }
            ],
        }
    )
    items = asyncio.run(make_client(handler).search_poi("故宫", city="北京", page=2))
    params = captured[0].url.params
    assert params["ak"] == AK
    assert params["query"] == "故宫"
    assert params["region"] == "北京"
    assert params["city_limit"] == "true"
    assert params["scope"] == "2"
    assert params["page_num"] == "1"  # page 2 -> 0 基
    assert params["output"] == "json"
    assert len(items) == 1
    hit = items[0]
    assert hit["source"] == "baidu"
    assert hit["source_poi_id"] == "e491ee79f4805b5d4355c2f7"
    assert hit["name"] == "故宫博物院"
    assert hit["city"] == "北京市"
    assert hit["category"] == "旅游景点"
    assert hit["rating"] == "4.8"
    assert hit["opening_hours"] == "08:30-17:00"
    # 坐标换回 GCJ-02：往返闭合
    g = bd09_to_gcj02(116.411354, 39.918058)
    assert hit["location"]["lon"] == pytest.approx(g[0], abs=1e-6)
    assert hit["location"]["lat"] == pytest.approx(g[1], abs=1e-6)


def test_search_poi_around_converts_location_to_bd09():
    handler, captured = ok_handler({"status": 0, "results": []})
    items = asyncio.run(
        make_client(handler).search_poi_around(
            "美食", location="116.391000,39.907000", radius=1000
        )
    )
    assert items == []
    params = captured[0].url.params
    b_lon, b_lat = gcj02_to_bd09(116.391, 39.907)
    lat_s, lng_s = params["location"].split(",")
    assert abs(float(lat_s) - b_lat) < 1e-5
    assert abs(float(lng_s) - b_lon) < 1e-5  # 百度序 lat,lng 且为 BD-09
    assert params["radius"] == "1000"


def test_search_poi_quota_exhausted_maps_to_shared_exception():
    for status in ("301", "302"):

        def handler(request: httpx.Request, _s=status) -> httpx.Response:
            return httpx.Response(
                200, json={"status": int(_s), "message": "天/永久配额超限"}
            )

        with pytest.raises(AmapQuotaExhaustedError):
            asyncio.run(make_client(handler).search_poi("x"))


def test_search_poi_error_raises_amap_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 20, "message": "APP不存在或被禁用"})

    with pytest.raises(AmapError) as ei:
        asyncio.run(make_client(handler).search_poi("x"))
    assert ei.value.infocode == "20"


# ---------- reverse geocoding ----------


def test_regeo_param_order_and_shape():
    handler, captured = ok_handler(
        {
            "status": 0,
            "result": {
                "formatted_address": "北京市东城区东长安街天安门",
                "addressComponent": {
                    "province": "北京市",
                    "city": "北京市",
                    "district": "东城区",
                },
            },
        }
    )
    info = asyncio.run(make_client(handler).regeo(lon=116.391, lat=39.907))
    params = captured[0].url.params
    b_lon, b_lat = gcj02_to_bd09(116.391, 39.907)
    lat_s, lng_s = params["location"].split(",")
    assert abs(float(lat_s) - b_lat) < 1e-5
    assert abs(float(lng_s) - b_lon) < 1e-5
    assert info == {
        "country": None,
        "province": "北京市",
        "city": "北京市",
        "district": "东城区",
        "address": "北京市东城区东长安街天安门",
    }


# ---------- weather/v1 ----------


def test_get_weather_live_shape():
    handler, captured = ok_handler(
        {
            "status": 0,
            "result": {
                "location": {"city": "北京市", "code": 110000},
                "now": {
                    "text": "晴",
                    "temp": -2,
                    "wind_dir": "东北风",
                    "wind_class": "3~4级",
                },
            },
        }
    )
    report = asyncio.run(make_client(handler).get_weather("110000", extensions="base"))
    assert captured[0].url.params["data_type"] == "now"
    # 省级码归一：110000 → 110100（2026-10-28 实测百度不收 XX0000）
    assert captured[0].url.params["district_id"] == "110100"
    assert report["kind"] == "live"
    assert report["city"] == "北京市"
    assert report["adcode"] == "110000"  # 落库键保持原始码
    assert report["payload"] == {
        "weather": "晴",
        "temperature": "-2",
        "wind_direction": "东北风",
        "wind_power": "3~4级",
        "humidity": None,
    }


def test_get_weather_forecast_strips_celsius():
    handler, captured = ok_handler(
        {
            "status": 0,
            "result": {
                "location": {"city": "北京市"},
                "forecasts": [
                    {
                        "date": "2026-10-28",
                        "text_day": "多云",
                        "text_night": "晴",
                        "high": "16°C",
                        "low": "4°C",
                        "wd_day": "北风",
                        "wc_day": "<3级",
                    }
                ],
            },
        }
    )
    report = asyncio.run(make_client(handler).get_weather("110000", extensions="all"))
    assert captured[0].url.params["data_type"] == "fc"
    assert report["kind"] == "forecast"
    cast = report["payload"]["casts"][0]
    assert cast == {
        "date": "2026-10-28",
        "day_weather": "多云",
        "night_weather": "晴",
        "day_temp": "16",
        "night_temp": "4",
        "day_wind": "北风",
        "day_wind_power": "<3级",
    }


# ---------- direction/v2/walking ----------


WALK_BODY = {
    "status": 0,
    "result": {
        "routes": [
            {
                "distance": 1200,
                "duration": 900,
                "steps": [
                    {
                        "distance": 500,
                        "duration": 360,
                        "instructions": "沿东长安街向东步行500米",
                        "road_name": "东长安街",
                        # path 为 BD-09 'lng,lat' 串
                        "path": "116.415,39.910;116.420,39.911",
                    },
                    {
                        "distance": 700,
                        "duration": 540,
                        "instructions": "沿广场西侧路向北步行700米",
                        "path": "116.420,39.911;116.421,39.917",
                    },
                ],
            }
        ]
    },
}


def test_walking_route_converts_path_to_gcj02():
    handler, captured = ok_handler(WALK_BODY)
    route = asyncio.run(
        make_client(handler).walking_route(
            "116.391000,39.907000", "116.413000,39.910000"
        )
    )
    params = captured[0].url.params
    # origin 已换 BD-09 且为 lat,lng 序
    b_lon, b_lat = gcj02_to_bd09(116.391, 39.907)
    lat_s, lng_s = params["origin"].split(",")
    assert abs(float(lat_s) - b_lat) < 1e-5
    assert abs(float(lng_s) - b_lon) < 1e-5
    assert route["distance_m"] == 1200
    assert route["duration_s"] == 900
    assert len(route["steps"]) == 2
    step = route["steps"][0]
    assert step["instruction"] == "沿东长安街向东步行500米"
    assert step["road"] == "东长安街"
    assert step["distance_m"] == 500
    # polyline 两点换回 GCJ-02 闭合
    g0 = bd09_to_gcj02(116.415, 39.910)
    assert step["polyline"][0]["lon"] == pytest.approx(g0[0], abs=1e-6)
    assert step["polyline"][0]["lat"] == pytest.approx(g0[1], abs=1e-6)
    assert len(route["polyline"]) == 4


def test_walking_route_empty_routes_returns_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 0, "result": {"routes": []}})

    route = asyncio.run(
        make_client(handler).walking_route("116.391,39.907", "116.391,39.907")
    )
    assert route == {"distance_m": 0, "duration_s": None, "steps": [], "polyline": []}


def test_walking_route_timeout_maps_shared_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(AmapTimeoutError):
        asyncio.run(
            make_client(handler).walking_route("116.391,39.907", "116.413,39.910")
        )


# ---------- direction/v2/transit ----------


def test_transit_route_routes_container_shape():
    body = {
        "status": 0,
        "result": {
            "routes": [
                {
                    "distance": 8000,
                    "duration": 2400,
                    "steps": [
                        {
                            "type": "walking",
                            "distance": 400,
                            "duration": 300,
                            "instructions": "向东南步行400米",
                            "path": "116.415,39.910;116.417,39.910",
                        },
                        {
                            "type": "subway",
                            "distance": 7000,
                            "duration": 1800,
                            "vehicle": {"name": "地铁1号线"},
                        },
                    ],
                }
            ]
        },
    }
    handler, _ = ok_handler(body)
    plans = asyncio.run(
        make_client(handler).transit_route(
            "116.391,39.907", "116.45,39.92", city="北京"
        )
    )
    assert len(plans) == 1
    plan = plans[0]
    assert plan["duration_s"] == 2400
    assert plan["walking_distance_m"] == 400
    assert len(plan["segments"]) == 2
    assert plan["segments"][0]["walking"]["distance_m"] == 400
    assert plan["segments"][0]["rides"] == []
    ride = plan["segments"][1]["rides"][0]
    assert ride["kind"] == "railway"
    assert ride["name"] == "地铁1号线"
    assert plan["segments"][1]["walking"] is None


def test_transit_route_accepts_transits_container():
    """文档页不可达：transits 容器键名同样要能解析（防御双候选）。"""
    body = {
        "status": 0,
        "result": {
            "transits": [
                {
                    "duration": 1800,
                    "steps": [
                        {"type": "bus", "distance": 5000, "vehicle": {"name": "52路"}}
                    ],
                }
            ]
        },
    }
    handler, _ = ok_handler(body)
    plans = asyncio.run(
        make_client(handler).transit_route(
            "116.391,39.907", "116.45,39.92", city="北京"
        )
    )
    assert plans[0]["segments"][0]["rides"][0]["kind"] == "bus"
    assert plans[0]["segments"][0]["rides"][0]["name"] == "52路"


# ---------- routematrix ----------


def test_distance_walking():
    handler, captured = ok_handler(
        {
            "status": 0,
            "result": [
                {
                    "distance": {"value": 1000, "text": "1000米"},
                    "duration": {"value": 720},
                },
            ],
        }
    )
    rows = asyncio.run(
        make_client(handler).distance(["116.391,39.907"], "116.40,39.91")
    )
    params = captured[0].url.params
    assert params["origins"].count("|") == 0
    assert rows == [{"distance_m": 1000, "duration_s": 720}]


def test_distance_rejects_non_walking():
    with pytest.raises(AmapError):
        asyncio.run(
            make_client(ok_handler({})[0]).distance(
                ["116.391,39.907"], "116.40,39.91", type_=2
            )
        )
