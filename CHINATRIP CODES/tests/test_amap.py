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
