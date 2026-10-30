# -*- coding: utf-8 -*-
"""TencentClient 形状：同构出参 / 腾讯 status 120/121→配额异常 / 无城市不烧额。"""

import asyncio

import httpx
import pytest

from app.services.amap_client import AmapError, AmapQuotaExhaustedError
from app.services.tencent_client import TencentClient


def run(coro):
    return asyncio.run(coro)


def _client(handler) -> TencentClient:
    return TencentClient(ak="test-key", transport=httpx.MockTransport(handler))


def test_search_poi_normalizes_gcj_passthrough():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["keyword"] == "豫园"
        assert request.url.params["boundary"].startswith("region(上海")
        return httpx.Response(
            200,
            json={
                "status": 0,
                "data": [
                    {
                        "id": "t1",
                        "title": "豫园",
                        "address": "上海市黄浦区安仁街218号",
                        "location": {"lat": 31.227, "lng": 121.492},
                    }
                ],
            },
        )

    hits = run(_client(handler).search_poi("豫园", city="上海"))
    assert hits[0]["name"] == "豫园"
    assert hits[0]["source"] == "tencent"
    assert hits[0]["location"] == {"lon": 121.492, "lat": 31.227}
    assert hits[0]["address"].startswith("上海市")


def test_search_without_city_returns_empty_without_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call the API without city")

    assert run(_client(handler).search_poi("豫园")) == []


def test_regeo_prefers_formatted_recommend():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["location"] == "31.227000,121.492000"
        return httpx.Response(
            200,
            json={
                "status": 0,
                "result": {
                    "address": "上海市黄浦区安仁街218号",
                    "formatted_addresses": {"recommend": "黄浦区豫园"},
                    "address_components": {
                        "province": "上海市",
                        "city": "上海市",
                        "district": "黄浦区",
                    },
                },
            },
        )

    out = run(_client(handler).regeo(lon=121.492, lat=31.227))
    assert out["address"] == "黄浦区豫园"


@pytest.mark.parametrize("status", [120, 121])
def test_quota_statuses_raise_quota_error(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": status, "message": "此key已停用"})

    with pytest.raises(AmapQuotaExhaustedError):
        run(_client(handler).search_poi("豫园", city="上海"))


def test_no_walking_route_method():
    # vendor_policy["walking"] 不含 tencent：客户端本来就不提供步行路线
    assert not hasattr(TencentClient, "walking_route")


def test_network_error_maps_to_amap_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("getaddrinfo failed")

    with pytest.raises(AmapError) as excinfo:
        run(_client(handler).search_poi("foo", city="\u4e0a\u6d77"))
    assert "network error" in str(excinfo.value)
