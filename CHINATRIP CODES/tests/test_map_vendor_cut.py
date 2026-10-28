# -*- coding: utf-8 -*-
"""一键切图商（2026-10-28）：deeplinks 百度形态 + /api/v1/amap/provider 端点。

无网络、无 TestClient——compose_deeplink 纯函数直调；provider 端点直注 Settings。
"""

import asyncio

from app.api.amap import map_provider_info
from app.config import Settings
from app.services.deeplinks import compose_deeplink

NAME = "外滩"
LON, LAT = 121.490317, 31.23841


def run(coro):
    return asyncio.run(coro)


# --- deeplinks provider -------------------------------------------------


def test_deeplink_default_provider_is_amap():
    body = compose_deeplink("driving", NAME, LON, LAT)
    assert body["provider"] == "amap"
    assert body["app_deeplink"].startswith("amapuri://route/plan/")


def test_deeplink_baidu_driving_shapes():
    body = compose_deeplink("driving", NAME, LON, LAT, provider="baidu")
    assert body["provider"] == "baidu"
    assert body["app_deeplink"].startswith("baidumap://map/direction?")
    assert "destination=31.23841,121.490317:" in body["app_deeplink"]  # 百度 lat,lng 序
    assert "coord_type=gcj02" in body["app_deeplink"]
    assert body["web_fallback"].startswith("https://api.map.baidu.com/direction?")
    assert "mode=driving" in body["web_fallback"]
    assert "output=html" in body["web_fallback"]


def test_deeplink_baidu_taxi_falls_back_to_direction():
    """百度无公开打车 scheme：taxi 档用驾车路线承接（App/网页一致）。"""
    body = compose_deeplink("taxi", NAME, LON, LAT, provider="baidu")
    assert body["mode"] == "taxi"
    assert body["app_deeplink"].startswith("baidumap://map/direction?")
    assert body["web_fallback"].startswith("https://api.map.baidu.com/direction?")


def test_deeplink_baidu_with_origin():
    body = compose_deeplink(
        "driving",
        NAME,
        LON,
        LAT,
        origin=("人民广场", 121.47, 31.23),
        provider="baidu",
    )
    assert "origin=31.23,121.47:" in body["app_deeplink"]
    assert "origin=31.23,121.47:" in body["web_fallback"]


def test_deeplink_baidu_name_is_url_encoded():
    body = compose_deeplink("driving", NAME, LON, LAT, provider="baidu")
    assert "%E5%A4%96%E6%BB%A9" in body["app_deeplink"]  # 「外滩」UTF-8 编码


def test_deeplink_bad_provider_raises():
    import pytest

    with pytest.raises(ValueError):
        compose_deeplink("driving", NAME, LON, LAT, provider="tencent")


# --- /api/v1/amap/provider ---------------------------------------------


def test_provider_endpoint_reports_baidu_ready():
    settings = Settings(
        llm_backend="mock", amap_api_key="", map_provider="baidu", baidu_ak="x"
    )
    body = run(map_provider_info(settings))
    assert body == {"provider": "baidu", "ready": True}


def test_provider_endpoint_reports_amap_not_ready():
    settings = Settings(llm_backend="mock", amap_api_key="", map_provider="amap")
    body = run(map_provider_info(settings))
    assert body == {"provider": "amap", "ready": False}
