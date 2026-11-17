# -*- coding: utf-8 -*-
"""城市回退点注册表单元（2026-11-04 P1#1 回退点入库闸）。

注册表=第四闸判定源：解析点=城市回退点→拒绝入库/不入池；行地址命中
回退地址族→不可作 geocode 依据。点值来源 tmp_unesco/poison_points.txt
（11-04 投毒普查多行聚簇）。
"""

from app.services.city_fallback import (
    CITY_FALLBACK_ADDRESS_TOKENS,
    CITY_FALLBACK_POINTS,
    FALLBACK_TOLERANCE_M,
    bare_city,
    is_city_fallback_point,
    is_fallback_address,
)


def test_registry_covers_poison_census_clusters():
    # tmp_unesco/poison_points.txt 11-04 普查的全部 ≥3 行同点聚簇城市
    assert set(CITY_FALLBACK_POINTS) == {"重庆", "苏州", "西安", "广州", "杭州", "通化"}
    assert "重庆" in CITY_FALLBACK_ADDRESS_TOKENS


def test_chongqing_gov_point_is_fallback():
    assert is_city_fallback_point(106.550464, 29.563761, "重庆")
    assert is_city_fallback_point(106.550464, 29.563761, "重庆市")  # 裸名兼容


def test_tolerance_window():
    # 容差内（重解析/provider 微差）算回退点
    assert is_city_fallback_point(106.550500, 29.563800, "重庆")
    # 解放碑（~2.5km 外）不误伤
    assert not is_city_fallback_point(106.577, 29.5586, "重庆")


def test_unknown_city_and_bad_coords_are_not_fallback():
    assert not is_city_fallback_point(104.06, 30.65, "成都")  # 未注册城市
    assert not is_city_fallback_point(None, 29.563761, "重庆")
    assert not is_city_fallback_point(106.550464, None, "重庆")
    assert not is_city_fallback_point("x", "y", "重庆")  # 非数值不抛


def test_cross_city_lookup_uses_row_city():
    # 同一坐标按行城市查表：重庆回退点在西安行上不是回退点
    assert not is_city_fallback_point(106.550464, 29.563761, "西安")


def test_fallback_address_family():
    assert is_fallback_address("重庆市渝中区上清寺人民支路69号", "重庆")
    assert is_fallback_address("人民支路69号附2", "重庆")
    assert not is_fallback_address("南川区南城街道", "重庆")  # 手工正址不误伤
    assert not is_fallback_address("渝中区上清寺", "苏州")  # 城市不匹配不误伤
    assert not is_fallback_address(None, "重庆")


def test_bare_city():
    assert bare_city("重庆市") == "重庆"
    assert bare_city(" 重庆 ") == "重庆"
    assert bare_city(None) == ""


def test_tolerance_value():
    # 政府驻地与最近真实景点（解放碑）≥1km；容差只需盖 provider 重解析微差
    assert FALLBACK_TOLERANCE_M == 150
