import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.amap import get_amap_client, router
from app.config import Settings, get_settings
from app.services.amap_client import AmapClient, AmapError, AmapTimeoutError

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
    second = items[1]
    assert second["location"] is None
    assert second["city"] == "江苏省"
    assert API_KEY not in json.dumps(items, ensure_ascii=False)


def test_client_status_zero_raises_amap_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ERROR_BODY)

    with pytest.raises(AmapError) as excinfo:
        asyncio.run(make_client(handler).search_poi("food"))
    assert excinfo.value.infocode == "10001"
    assert "INVALID_USER_KEY" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


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
