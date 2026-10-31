# -*- coding: utf-8 -*-
"""图商功能优先级策略（2026-10-30 按三家免费配额富裕度拍板）。"""

from app.config import Settings
from app.services.map_provider import (
    FUNCTION_PROVIDER_PRIORITY,
    build_client_chain,
    build_vendor,
)


def _settings(*, amap: str = "", baidu: str = "", tencent: str = "") -> Settings:
    return Settings(
        _env_file=None,
        map_provider="baidu",
        baidu_ak=baidu,
        amap_api_key=amap,
        tencent_map_key=tencent,
    )


def test_search_priority_amap_tencent_baidu():
    assert FUNCTION_PROVIDER_PRIORITY["search"] == ("amap", "tencent", "baidu")


def test_regeo_priority_baidu_amap_tencent():
    assert FUNCTION_PROVIDER_PRIORITY["regeo"] == ("baidu", "amap", "tencent")


def test_walking_chain_excludes_tencent():
    # TencentClient 无 walking_route：步行链只有 baidu/amap
    assert "tencent" not in FUNCTION_PROVIDER_PRIORITY["walking"]


def test_chain_full_order_for_search():
    chain = build_client_chain(_settings(amap="a", baidu="b", tencent="t"), "search")
    assert [c.vendor for c in chain] == ["amap", "tencent", "baidu"]


def test_chain_skips_keyless_vendors():
    chain = build_client_chain(_settings(baidu="b"), "search")
    assert [c.vendor for c in chain] == ["baidu"]


def test_chain_empty_when_no_keys():
    assert build_client_chain(_settings(), "regeo") == []


def test_regeo_chain_starts_with_baidu():
    chain = build_client_chain(_settings(amap="a", baidu="b", tencent="t"), "regeo")
    assert [c.vendor for c in chain] == ["baidu", "amap", "tencent"]


def test_walking_chain_has_no_tencent_even_with_key():
    chain = build_client_chain(_settings(amap="a", baidu="b", tencent="t"), "walking")
    assert [c.vendor for c in chain] == ["baidu", "amap"]


def test_build_vendor_unknown_returns_none():
    assert build_vendor("here", _settings(baidu="b")) is None


def test_transit_chain_baidu_amap():
    chain = build_client_chain(_settings(amap="a", baidu="b", tencent="t"), "transit")
    assert [c.vendor for c in chain] == ["baidu", "amap"]
