# -*- coding: utf-8 -*-
"""/api/v1/hotels/search 手输酒店名验证搜索（2026-11-07 每晚酒店卡）。

口径：复用检索链（amap>tencent>baidu，run_vendor_chain），酒店类目命中
排前（稳定排序，同组内保持图商序）；图商未配置 503 / 超时 504 / 全灭
502 / 参数非法 422——与 /api/v1/amap/poi/search 同构。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.amap import get_search_chain
from app.api.hotels import router as hotels_router
from app.config import Settings, get_settings
from app.services.amap_client import AmapError, AmapTimeoutError

HEADERS = {"X-Device-ID": "device-1"}


class _StubHotelClient:
    vendor = "stub"  # 独立 vendor 名：不碰共享配额闩（_SEARCH_LATCH）

    async def search_poi(self, keywords, *, city=None, page=1):
        return [
            {
                "source": "amap",
                "source_poi_id": "B0HOTEL1",
                "name": "全季酒店",
                "city": city or "北京",
                "category": "住宿服务:酒店宾馆",
                "address": "东城区金鱼胡同1号",
                "location": {"lon": 116.41, "lat": 39.91},
                "opening_hours": None,
                "rating": "4.5",
            },
            {
                "source": "amap",
                "source_poi_id": "B0SIGHT1",
                "name": "故宫博物院",
                "city": city or "北京",
                "category": "风景名胜;风景名胜相关",
                "address": "景山前街4号",
                "location": {"lon": 116.397, "lat": 39.918},
                "opening_hours": None,
                "rating": None,
            },
        ]


class _ExplodingClient:
    vendor = "stub"  # 独立 vendor 名：不碰共享配额闩（_SEARCH_LATCH）

    def __init__(self, exc):
        self._exc = exc

    async def search_poi(self, keywords, *, city=None, page=1):
        raise self._exc


def _make_app(settings=None, chain=None) -> FastAPI:
    app = FastAPI()
    app.include_router(hotels_router)
    app.dependency_overrides[get_settings] = lambda: (
        settings or Settings(llm_backend="mock", amap_api_key="k", map_provider="amap")
    )
    if chain is not None:
        app.dependency_overrides[get_search_chain] = lambda: chain
    return app


def _get(client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/v1/hotels/search?{qs}", headers=HEADERS)


def test_search_ranks_hotel_category_first():
    with TestClient(_make_app(chain=[_StubHotelClient()])) as client:
        resp = _get(client, keywords="全季", city="北京")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["name"] for i in items] == ["全季酒店", "故宫博物院"]
    assert items[0]["is_hotel"] is True
    assert items[0]["address"] == "东城区金鱼胡同1号"
    assert items[0]["location"] == {"lon": 116.41, "lat": 39.91}
    assert items[0]["source_poi_id"] == "B0HOTEL1"
    assert items[1]["is_hotel"] is False  # 酒店类目优先，非酒店殿后


def test_search_422_on_blank_keywords():
    with TestClient(_make_app(chain=[_StubHotelClient()])) as client:
        assert _get(client, keywords="", city="北京").status_code == 422


def test_search_503_when_chain_empty():
    # 空链=图商未配置口径（测试永不打真图商 API）
    with TestClient(_make_app(chain=[])) as client:
        resp = _get(client, keywords="全季")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "amap_not_configured"


def test_search_504_on_timeout_and_502_on_error():
    timeout_app = _make_app(chain=[_ExplodingClient(AmapTimeoutError("slow"))])
    with TestClient(timeout_app) as client:
        resp = _get(client, keywords="全季")
    assert resp.status_code == 504
    assert resp.json()["detail"] == "amap_timeout"

    error_app = _make_app(chain=[_ExplodingClient(AmapError("boom", "40000"))])
    with TestClient(error_app) as client:
        resp = _get(client, keywords="全季")
    assert resp.status_code == 502
    assert resp.json()["detail"] == "amap_error"
