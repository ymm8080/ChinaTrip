"""price_band 档位与 amap cost 抽取单测（DESIGN §四 / price_level 链）。"""


from app.services.amap_client import _hours_result, _parse_cost
from app.services.price_band import band_for_cost


def test_band_boundaries():
    """半开区间：(50,100] 归 value，50 元整归 budget。"""
    assert band_for_cost(50) == "budget"
    assert band_for_cost(50.0) == "budget"
    assert band_for_cost(50.01) == "value"
    assert band_for_cost(100) == "value"
    assert band_for_cost(100.5) == "mid"
    assert band_for_cost(200) == "mid"
    assert band_for_cost(500) == "upper"
    assert band_for_cost(501) == "premium"
    assert band_for_cost(3000) == "premium"


def test_band_invalid():
    assert band_for_cost(None) is None
    assert band_for_cost("abc") is None
    assert band_for_cost(0) is None
    assert band_for_cost(-5) is None
    assert band_for_cost(10000) is None  # 越界不猜
    assert band_for_cost("58.5") == "value"


def test_parse_cost_forms():
    assert _parse_cost("58") == 58.0
    assert _parse_cost("58.5") == 58.5
    assert _parse_cost("¥128") == 128.0
    assert _parse_cost(None) is None
    assert _parse_cost("") is None
    assert _parse_cost("人均") is None  # 无数字不猜
    assert _parse_cost("0.5") is None  # 过闸 1-9999


def test_hours_result_surfaces_cost():
    poi = {
        "name": "全聚德烤鸭店(前门店)",
        "id": "B000A8UIN8",
        "address": "北京市东城区前门大街30号",
        "business": {
            "opentime_week": "周一至周日 10:00-22:00",
            "rating": "4.5",
            "cost": "158.0",
        },
    }
    res = _hours_result(poi)
    assert res["cost"] == 158.0
    # 景点类无 cost 键 → 结果缺省不落键
    res2 = _hours_result({"name": "故宫博物院", "business": {"rating": "4.8"}})
    assert "cost" not in res2
