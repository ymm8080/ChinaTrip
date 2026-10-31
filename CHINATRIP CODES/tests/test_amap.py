import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.amap import (
    get_amap_client,
    get_regeo_chain,
    get_search_chain,
    router,
)
from app.config import Settings, get_settings
from app.services.amap_client import (
    AmapClient,
    AmapError,
    AmapQuotaExhaustedError,
    AmapTimeoutError,
    _normalize_poi,
)

API_KEY = "test-key-123"
BASE_URL = "https://restapi.amap.test/v3"

SUCCESS_BODY = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "pois": [
        {
            "id": "B000A7BD6C",
            "name": "上海人民广场",
            "type": "风景名胜;公园广场;城市广场",
            "typecode": "110202",
            "address": "人民大道120号",
            "location": "121.473667,31.230525",
            "pname": "上海市",
            "cityname": "上海市",
            "biz_ext": {"opening": "全年 周一至周日 05:00-23:00", "rating": "4.7"},
            "photos": [
                {"title": "人民广场全景", "url": "https://aos-comment.amap.com/1.jpg"},
                {"title": "无链接图", "url": []},
            ],
        },
        {
            "id": "B0FFI9BOII",
            "name": "无名点位",
            "type": "",
            "typecode": "",
            "address": "",
            "location": "",
            "pname": "江苏省",
            "cityname": [],
            "biz_ext": [],
        },
    ],
}

ERROR_BODY = {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}

WALKING_BODY = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "route": {
        "paths": [
            {
                "distance": "350",
                "duration": "280",
                "steps": [
                    {
                        "instruction": "沿南京西路向东步行120米右转",
                        "road": "南京西路",
                        "distance": "120",
                        "orientation": "东",
                        "polyline": "121.473667,31.230525;121.475000,31.231000",
                    },
                    {
                        "instruction": "沿西藏中路向南步行230米到达终点",
                        "road": "西藏中路",
                        "distance": "230",
                        "orientation": "南",
                        "polyline": "121.475000,31.231000;121.475500,31.229000",
                    },
                ],
            }
        ]
    },
}

TRANSIT_BODY = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "route": {
        "transits": [
            {
                "cost": "4.0",
                "duration": "1500",
                "walking_distance": "320",
                "segments": [
                    {
                        "walking": {
                            "distance": "320",
                            "duration": "280",
                            "steps": [
                                {
                                    "instruction": "沿人民大道向西步行320米右转",
                                    "road": "人民大道",
                                    "step_distance": "320",
                                    "orientation": "西",
                                    "polyline": "121.4737,31.2305;121.4720,31.2308",
                                }
                            ],
                        }
                    },
                    {
                        "bus": {
                            "buslines": [
                                {
                                    "name": "地铁2号线(徐泾东--广兰路)",
                                    "type": "地铁线路",
                                    "departure_stop": {"name": "人民广场站"},
                                    "arrival_stop": {"name": "世纪大道站"},
                                    "via_num": "5",
                                    "departure_time": "06:00",
                                }
                            ]
                        }
                    },
                ],
            },
            {
                "cost": "58.5",
                "duration": "2700",
                "walking_distance": "150",
                "segments": [
                    {
                        "walking": {
                            "distance": "150",
                            "duration": "120",
                            "steps": [],
                        }
                    },
                    {
                        "railway": {
                            "railways": [
                                {
                                    "name": "G7501",
                                    "departure_stop": {"name": "上海虹桥站"},
                                    "arrival_stop": {"name": "苏州北站"},
                                    "via_num": "2",
                                    "departure_time": "08:30",
                                }
                            ]
                        }
                    },
                ],
            },
        ]
    },
}


def make_settings(api_key: str = API_KEY) -> Settings:
    return Settings(
        amap_api_key=api_key,
        amap_base_url=BASE_URL,
        amap_timeout_seconds=1.0,
        # 钉死提供方:pydantic 会读真实 .env,地图切 baidu 时不得影响本测试
        map_provider="amap",
    )


def make_client(handler) -> AmapClient:
    return AmapClient(
        key=API_KEY,
        base_url=BASE_URL,
        timeout_seconds=1.0,
        transport=httpx.MockTransport(handler),
    )


def make_app(handler=None, api_key: str = API_KEY) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    settings = make_settings(api_key)
    app.dependency_overrides[get_settings] = lambda: settings
    if handler is not None:
        amap = make_client(handler)
        app.dependency_overrides[get_search_chain] = lambda: [amap]
        app.dependency_overrides[get_regeo_chain] = lambda: [amap]
        app.dependency_overrides[get_amap_client] = lambda: amap
    return app


def ok_handler(body: dict):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=body)

    return handler, captured


def test_client_success_normalizes_and_carries_key():
    handler, captured = ok_handler(SUCCESS_BODY)
    items = asyncio.run(make_client(handler).search_poi("food", city="上海", page=2))
    params = captured[0].url.params
    assert params["key"] == API_KEY
    assert params["keywords"] == "food"
    assert params["city"] == "上海"
    assert params["citylimit"] == "true"
    assert params["page"] == "2"
    assert len(items) == 2
    first = items[0]
    assert first["source"] == "amap"
    assert first["source_poi_id"] == "B000A7BD6C"
    assert first["name"] == "上海人民广场"
    assert first["city"] == "上海市"
    assert first["category"] == "风景名胜;公园广场;城市广场"
    assert first["address"] == "人民大道120号"
    assert first["location"] == {"lon": 121.473667, "lat": 31.230525}
    assert first["opening_hours"] == "全年 周一至周日 05:00-23:00"
    assert first["rating"] == "4.7"
    assert first["photos"] == [
        {"url": "https://aos-comment.amap.com/1.jpg", "title": "人民广场全景"}
    ]
    second = items[1]
    assert second["location"] is None
    assert second["city"] == "江苏省"
    assert second["opening_hours"] is None
    assert second["rating"] is None
    assert "photos" not in second  # 无 photos 键不炸、不落空键
    assert API_KEY not in json.dumps(items, ensure_ascii=False)


def test_client_status_zero_raises_amap_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ERROR_BODY)

    with pytest.raises(AmapError) as excinfo:
        asyncio.run(make_client(handler).search_poi("food"))
    assert excinfo.value.infocode == "10001"
    assert "INVALID_USER_KEY" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_client_quota_exhausted_raises_quota_error():
    # v3 text 的 10021 须浮出专用异常，match_and_enrich 熔断才有信号
    handler, _ = ok_handler(QUOTA_BODY)
    with pytest.raises(AmapQuotaExhaustedError) as excinfo:
        asyncio.run(make_client(handler).search_poi("food"))
    assert excinfo.value.infocode == "10021"


def test_client_connect_timeout_raises_timeout_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectTimeout("connect timed out")

    with pytest.raises(AmapTimeoutError):
        asyncio.run(make_client(handler).search_poi("food"))


def test_client_invalid_json_raises_amap_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    with pytest.raises(AmapError):
        asyncio.run(make_client(handler).search_poi("food"))


def test_endpoint_success():
    handler, captured = ok_handler(SUCCESS_BODY)
    with TestClient(make_app(handler)) as client:
        resp = client.get(
            "/api/v1/amap/poi/search",
            params={"keywords": "food", "city": "上海", "page": 2},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["location"] == {"lon": 121.473667, "lat": 31.230525}
    assert captured[0].url.params["key"] == API_KEY
    assert API_KEY not in resp.text


def test_endpoint_empty_pois_returns_empty_items():
    handler, _ = ok_handler(
        {"status": "1", "info": "OK", "infocode": "10000", "pois": []}
    )
    with TestClient(make_app(handler)) as client:
        resp = client.get("/api/v1/amap/poi/search", params={"keywords": "food"})
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "page": 1}


def test_endpoint_amap_error_returns_502():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ERROR_BODY)

    with TestClient(make_app(handler)) as client:
        resp = client.get("/api/v1/amap/poi/search", params={"keywords": "food"})
    assert resp.status_code == 502
    assert resp.json() == {"detail": "amap_error"}
    assert API_KEY not in resp.text
    assert "10001" not in resp.text
    assert "INVALID_USER_KEY" not in resp.text


def test_endpoint_timeout_returns_504():
    def handler(request: httpx.Request):
        raise httpx.ConnectTimeout("connect timed out")

    with TestClient(make_app(handler)) as client:
        resp = client.get("/api/v1/amap/poi/search", params={"keywords": "food"})
    assert resp.status_code == 504
    assert resp.json() == {"detail": "amap_timeout"}


def test_endpoint_not_configured_returns_503():
    with TestClient(make_app(api_key="")) as client:
        resp = client.get("/api/v1/amap/poi/search", params={"keywords": "food"})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "amap_not_configured"}


@pytest.mark.parametrize(
    "params",
    [
        {"keywords": ""},
        {"keywords": "x" * 65},
        {"keywords": "food", "page": 0},
    ],
)
def test_endpoint_validation_returns_422(params):
    with TestClient(make_app()) as client:
        resp = client.get("/api/v1/amap/poi/search", params=params)
    assert resp.status_code == 422


def test_walking_route_success_normalizes_steps_and_polyline():
    handler, captured = ok_handler(WALKING_BODY)
    client = make_client(handler)
    result = asyncio.run(client.walking_route("121.4737,31.2305", "121.4755,31.2290"))
    params = captured[0].url.params
    assert params["key"] == API_KEY
    assert params["origin"] == "121.4737,31.2305"
    assert params["destination"] == "121.4755,31.2290"
    assert params["output"] == "JSON"
    assert result["distance_m"] == 350  # path-level distance is authoritative
    assert result["duration_s"] == 280  # real v3 walking payload carries duration
    assert len(result["steps"]) == 2
    first = result["steps"][0]
    assert first["instruction"] == "沿南京西路向东步行120米右转"
    assert first["road"] == "南京西路"
    assert first["distance_m"] == 120
    assert first["orientation"] == "东"
    assert first["polyline"] == [
        {"lon": 121.473667, "lat": 31.230525},
        {"lon": 121.475, "lat": 31.231},
    ]
    assert result["polyline"] == [
        {"lon": 121.473667, "lat": 31.230525},
        {"lon": 121.475, "lat": 31.231},
        {"lon": 121.475, "lat": 31.231},
        {"lon": 121.4755, "lat": 31.229},
    ]
    assert API_KEY not in json.dumps(result, ensure_ascii=False)


def test_walking_route_empty_paths_returns_zero_shape():
    handler, _ = ok_handler(
        {"status": "1", "info": "OK", "infocode": "10000", "route": {"paths": []}}
    )
    client = make_client(handler)
    result = asyncio.run(client.walking_route("121.4737,31.2305", "121.4737,31.2305"))
    assert result == {"distance_m": 0, "duration_s": None, "steps": [], "polyline": []}


def test_walking_route_status_zero_raises_amap_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ERROR_BODY)

    client = make_client(handler)
    with pytest.raises(AmapError) as excinfo:
        asyncio.run(client.walking_route("121.4737,31.2305", "121.4755,31.2290"))
    assert excinfo.value.infocode == "10001"
    assert "INVALID_USER_KEY" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_walking_route_timeout_raises_timeout_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectTimeout("connect timed out")

    client = make_client(handler)
    with pytest.raises(AmapTimeoutError):
        asyncio.run(client.walking_route("121.4737,31.2305", "121.4755,31.2290"))


def test_transit_route_success_normalizes_plans():
    handler, captured = ok_handler(TRANSIT_BODY)
    client = make_client(handler)
    plans = asyncio.run(
        client.transit_route(
            "121.4737,31.2305", "120.5853,31.2988", city="上海", cityd="苏州"
        )
    )
    params = captured[0].url.params
    assert params["key"] == API_KEY
    assert params["origin"] == "121.4737,31.2305"
    assert params["destination"] == "120.5853,31.2988"
    assert params["city"] == "上海"
    assert params["cityd"] == "苏州"
    assert len(plans) == 2
    bus_plan = plans[0]
    assert bus_plan["cost_yuan"] == 4.0
    assert bus_plan["duration_s"] == 1500
    assert bus_plan["walking_distance_m"] == 320
    walking_seg = bus_plan["segments"][0]["walking"]
    assert walking_seg["distance_m"] == 320
    assert walking_seg["duration_s"] == 280
    assert walking_seg["steps"][0]["road"] == "人民大道"
    bus_seg = bus_plan["segments"][1]
    assert bus_seg["walking"] is None
    ride = bus_seg["rides"][0]
    assert ride["kind"] == "bus"
    assert ride["name"] == "地铁2号线(徐泾东--广兰路)"
    assert ride["type"] == "地铁线路"
    assert ride["departure_stop"] == "人民广场站"
    assert ride["arrival_stop"] == "世纪大道站"
    assert ride["via_stops"] == 5
    assert ride["departure_time"] == "06:00"
    rail_plan = plans[1]
    assert rail_plan["cost_yuan"] == 58.5
    assert rail_plan["duration_s"] == 2700
    rail_ride = rail_plan["segments"][1]["rides"][0]
    assert rail_ride["kind"] == "railway"
    assert rail_ride["type"] is None
    assert rail_ride["via_stops"] == 2
    assert rail_ride["departure_stop"] == "上海虹桥站"
    assert API_KEY not in json.dumps(plans, ensure_ascii=False)


def test_transit_route_without_cityd_omits_param():
    handler, captured = ok_handler(TRANSIT_BODY)
    client = make_client(handler)
    asyncio.run(
        client.transit_route("121.4737,31.2305", "121.5853,31.2988", city="上海")
    )
    params = captured[0].url.params
    assert "cityd" not in params


def test_transit_route_empty_transits_returns_empty_list():
    handler, _ = ok_handler(
        {"status": "1", "info": "OK", "infocode": "10000", "route": {"transits": []}}
    )
    client = make_client(handler)
    plans = asyncio.run(
        client.transit_route("121.4737,31.2305", "121.5853,31.2988", city="上海")
    )
    assert plans == []


def test_transit_route_caps_at_three_plans():
    transit = {"cost": "1", "duration": "60", "walking_distance": "0", "segments": []}
    handler, _ = ok_handler(
        {
            "status": "1",
            "info": "OK",
            "infocode": "10000",
            "route": {"transits": [transit] * 4},
        }
    )
    client = make_client(handler)
    plans = asyncio.run(
        client.transit_route("121.4737,31.2305", "121.5853,31.2988", city="上海")
    )
    assert len(plans) == 3


REGEO_BODY = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "regeocode": {
        "formatted_address": "北京市东城区景山前街4号",
        "addressComponent": {
            "country": "中国",
            "province": "北京市",
            "city": [],
            "district": "东城区",
        },
    },
}


def test_client_regeo_municipality_city_falls_back_to_province():
    handler, captured = ok_handler(REGEO_BODY)
    info = asyncio.run(make_client(handler).regeo(lon=116.397, lat=39.917))
    params = captured[0].url.params
    assert captured[0].url.path.endswith("/geocode/regeo")
    assert params["key"] == API_KEY
    assert params["location"] == "116.397000,39.917000"
    assert info["city"] == "北京市"
    assert info["province"] == "北京市"
    assert info["district"] == "东城区"
    assert info["address"] == "北京市东城区景山前街4号"
    assert API_KEY not in json.dumps(info, ensure_ascii=False)


def test_client_regeo_prefers_city_over_province():
    body = {
        "status": "1",
        "info": "OK",
        "infocode": "10000",
        "regeocode": {
            "formatted_address": "江苏省苏州市姑苏区",
            "addressComponent": {
                "country": "中国",
                "province": "江苏省",
                "city": "苏州市",
                "district": [],
            },
        },
    }
    handler, _ = ok_handler(body)
    info = asyncio.run(make_client(handler).regeo(lon=120.585, lat=31.299))
    assert info["city"] == "苏州市"
    assert info["province"] == "江苏省"
    assert info["district"] is None


def test_endpoint_regeo_success():
    handler, _ = ok_handler(REGEO_BODY)
    with TestClient(make_app(handler)) as client:
        resp = client.get("/api/v1/amap/regeo", params={"lon": 116.397, "lat": 39.917})
    assert resp.status_code == 200
    body = resp.json()
    assert body["city"] == "北京市"
    assert body["address"] == "北京市东城区景山前街4号"
    assert API_KEY not in resp.text


def test_endpoint_regeo_not_configured_returns_503():
    with TestClient(make_app(api_key="")) as client:
        resp = client.get("/api/v1/amap/regeo", params={"lon": 116.397, "lat": 39.917})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "amap_not_configured"}


@pytest.mark.parametrize(
    "params",
    [
        {"lon": 200, "lat": 39.9},
        {"lon": 116.4, "lat": 100},
        {"lon": 116.4},
    ],
)
def test_endpoint_regeo_validation_returns_422(params):
    with TestClient(make_app()) as client:
        resp = client.get("/api/v1/amap/regeo", params=params)
    assert resp.status_code == 422


IP_BODY = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "province": "上海市",
    "city": "上海市",
    "adcode": "310000",
    "rectangle": "121.3159,30.7567;121.8084,31.4379",
}


def test_client_ip_locate_success():
    handler, captured = ok_handler(IP_BODY)
    info = asyncio.run(make_client(handler).ip_locate())
    assert captured[0].url.path.endswith("/ip")
    assert captured[0].url.params["key"] == API_KEY
    assert "ip" not in captured[0].url.params
    assert info == {"province": "上海市", "city": "上海市", "adcode": "310000"}
    assert API_KEY not in json.dumps(info, ensure_ascii=False)


def test_client_ip_locate_unknown_city_falls_back_to_province():
    handler, _ = ok_handler(
        {
            "status": "1",
            "info": "OK",
            "infocode": "10000",
            "province": "江苏省",
            "city": "",
        }
    )
    info = asyncio.run(make_client(handler).ip_locate())
    assert info["city"] == "江苏省"
    assert info["adcode"] is None


def test_endpoint_ip_locate_success():
    handler, _ = ok_handler(IP_BODY)
    with TestClient(make_app(handler)) as client:
        resp = client.get("/api/v1/amap/ip")
    assert resp.status_code == 200
    assert resp.json()["city"] == "上海市"
    assert API_KEY not in resp.text


def test_endpoint_ip_locate_not_configured_returns_503():
    with TestClient(make_app(api_key="")) as client:
        resp = client.get("/api/v1/amap/ip")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "amap_not_configured"}


def test_normalize_poi_accepts_v5_style_top_level_hours():
    poi = {
        "id": "B001",
        "name": "某景点",
        "location": "121.47,31.23",
        "opentime_today": "08:00-18:00",
    }
    assert _normalize_poi(poi)["opening_hours"] == "08:00-18:00"


def test_normalize_poi_photos_v3_v5_shapes_and_missing_key():
    v3 = _normalize_poi(
        {
            "name": "A",
            "photos": [
                {"title": "全景", "url": "https://x/1.jpg"},
                {"title": [], "url": []},  # 空 url 丢弃
                {"title": "缺链接"},
                "junk",  # 非字典丢弃
            ],
        }
    )
    assert v3["photos"] == [{"url": "https://x/1.jpg", "title": "全景"}]
    v5 = _normalize_poi(
        {"name": "B", "photos": [{"title": [], "url": "https://x/2.jpg"}]}
    )
    assert v5["photos"] == [{"url": "https://x/2.jpg", "title": None}]
    assert "photos" not in _normalize_poi({"name": "C"})
    assert "photos" not in _normalize_poi({"name": "D", "photos": []})
    assert "photos" not in _normalize_poi({"name": "E", "photos": "not-a-list"})


def test_normalize_poi_prefers_biz_ext_over_v5_fields():
    poi = {
        "name": "某景点",
        "biz_ext": {"opening": "全年 全天开放"},
        "opentime_today": "08:00-18:00",
    }
    assert _normalize_poi(poi)["opening_hours"] == "全年 全天开放"


def test_distance_parses_walking_results():
    body = {
        "status": "1",
        "info": "OK",
        "infocode": "10000",
        "count": "2",
        "results": [
            {"origin_id": "1", "dest_id": "1", "distance": "1234", "duration": "900"},
            {"origin_id": "2", "dest_id": "1", "distance": "0", "duration": "0"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/distance")
        assert request.url.params["type"] == "1"
        assert request.url.params["origins"].count("|") == 1
        return httpx.Response(200, json=body)

    out = asyncio.run(
        make_client(handler).distance(["116.4,39.9", "116.5,39.9"], "116.6,39.9")
    )
    assert out == [
        {"distance_m": 1234, "duration_s": 900},
        {"distance_m": 0, "duration_s": 0},
    ]


QUOTA_BODY = {
    "status": "0",
    "info": "USER_DAILY_QUERY_OVER_LIMIT",
    "infocode": "10021",
}

V5_AROUND_OK_BODY = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "pois": [
        {
            "id": "B000A8UIN8",
            "name": "故宫博物院",
            "address": "景山前街4号",
            "business": {
                "opentime_week": "周二-周日 08:30-17:00（16:00停止入院）",
                "rating": "4.9",
            },
        }
    ],
}


def test_search_hours_text_quota_raises_quota_error():
    # 10021 从 _request_json 路径浮出为专用异常（AmapError 子类）
    handler, captured = ok_handler(QUOTA_BODY)
    with pytest.raises(AmapQuotaExhaustedError) as excinfo:
        asyncio.run(make_client(handler).search_hours("故宫博物院"))
    assert isinstance(excinfo.value, AmapError)
    assert excinfo.value.infocode == "10021"
    assert captured[0].url.path.endswith("/v5/place/text")


def test_search_hours_without_location_no_around_fallback():
    handler, captured = ok_handler(QUOTA_BODY)
    with pytest.raises(AmapQuotaExhaustedError):
        asyncio.run(make_client(handler).search_hours("故宫博物院"))
    assert len(captured) == 1  # 无 location 不做 around 兜底


def test_search_hours_quota_falls_back_to_around_and_returns_hit():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/v5/place/text"):
            return httpx.Response(200, json=QUOTA_BODY)
        return httpx.Response(200, json=V5_AROUND_OK_BODY)

    result = asyncio.run(
        make_client(handler).search_hours(
            "故宫博物院", "北京", location="116.397,39.917"
        )
    )
    assert calls[0].url.path.endswith("/v5/place/text")
    assert calls[1].url.path.endswith("/v5/place/around")
    around_params = calls[1].url.params
    assert around_params["keywords"] == "故宫博物院"
    assert around_params["location"] == "116.397,39.917"
    assert around_params["radius"] == "3000"
    assert around_params["page_size"] == "1"
    assert around_params["show_fields"] == "business,photos"
    assert "city" not in around_params
    assert "city_limit" not in around_params
    assert result == {
        "opening_hours": "周二-周日 08:30-17:00（16:00停止入院）",
        "rating": "4.9",
        "matched": "故宫博物院",
        "address": "景山前街4号",
        "poi_id": "B000A8UIN8",
    }


def test_search_hours_around_also_quota_reraises_original_text_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=QUOTA_BODY)

    with pytest.raises(AmapQuotaExhaustedError) as excinfo:
        asyncio.run(
            make_client(handler).search_hours(
                "故宫博物院", "北京", location="116.397,39.917"
            )
        )
    assert excinfo.value.infocode == "10021"
    assert API_KEY not in str(excinfo.value)


def test_search_hours_non_quota_error_stays_plain_amap_error():
    handler, captured = ok_handler(ERROR_BODY)
    with pytest.raises(AmapError) as excinfo:
        asyncio.run(
            make_client(handler).search_hours(
                "故宫博物院", "北京", location="116.397,39.917"
            )
        )
    assert not isinstance(excinfo.value, AmapQuotaExhaustedError)
    assert excinfo.value.infocode == "10001"
    assert len(captured) == 1  # 非 10021 不触发 around 兜底


def test_search_hours_over_limit_info_without_infocode_still_quota_error():
    # amap 空串字段会以 [] 顶替 —— infocode 缺失时靠 info 兜底判配额
    handler, _ = ok_handler(
        {"status": "0", "info": "USER_DAILY_QUERY_OVER_LIMIT", "infocode": []}
    )
    with pytest.raises(AmapQuotaExhaustedError):
        asyncio.run(make_client(handler).search_hours("故宫博物院"))


def test_search_poi_around_quota_raises_quota_error():
    # _pois_from_response 路径（v3 /place/around）同样浮出专用异常
    handler, _ = ok_handler(QUOTA_BODY)
    with pytest.raises(AmapQuotaExhaustedError) as excinfo:
        asyncio.run(
            make_client(handler).search_poi_around(
                "故宫博物院", location="116.397,39.917"
            )
        )
    assert excinfo.value.infocode == "10021"


def test_client_connect_error_raises_amap_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("getaddrinfo failed")

    with pytest.raises(AmapError) as excinfo:
        asyncio.run(make_client(handler).search_poi("food"))
    assert "network error" in str(excinfo.value)


def test_endpoint_search_falls_back_when_first_vendor_quota_dead():
    def dead(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=QUOTA_BODY)

    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SUCCESS_BODY)

    app = make_app()
    ok_client = make_client(ok)
    ok_client.vendor = "baidu"  # vendor 需不同，否则首个配额死 latch 会连带跳过它
    app.dependency_overrides[get_search_chain] = lambda: [
        make_client(dead),
        ok_client,
    ]
    with TestClient(app) as client:
        resp = client.get("/api/v1/amap/poi/search", params={"keywords": "food"})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


def test_endpoint_poi_search_connect_error_returns_502():
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("getaddrinfo failed")

    app = make_app()
    app.dependency_overrides[get_search_chain] = lambda: [make_client(broken)]
    with TestClient(app) as client:
        resp = client.get("/api/v1/amap/poi/search", params={"keywords": "food"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "amap_error"


@pytest.fixture(autouse=True)
def _clear_amap_vendor_latches():
    """配额 latch 是模块级状态，测试间必须清零防串扰。"""
    from app.api import amap as amap_api

    amap_api._SEARCH_LATCH.clear()
    amap_api._REGEO_LATCH.clear()
    yield
    amap_api._SEARCH_LATCH.clear()
    amap_api._REGEO_LATCH.clear()


# --- _normalize_poi ename（双语 P1 补链 2026-10-30）-----------------------


def test_normalize_poi_keeps_ename():
    poi = _normalize_poi(
        {
            "id": "B000A7",
            "name": "东方明珠广播电视塔",
            "ename": "Oriental Pearl Radio and TV Tower",
            "cityname": "上海市",
            "type": "风景名胜;地标",
            "address": "世纪大道1号",
            "location": "121.499809,31.239666",
        }
    )
    assert poi["ename"] == "Oriental Pearl Radio and TV Tower"


def test_normalize_poi_without_ename_omits_key():
    poi = _normalize_poi({"id": "B1", "name": "无名点", "cityname": "上海市"})
    assert "ename" not in poi
