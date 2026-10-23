"""coords.py 单元测试：坐标转换、make_point、haversine_m（纯函数，无 DB/网络）。"""

import re

import pytest
from geoalchemy2.elements import WKTElement

from app.services.coords import (
    gcj02_to_wgs84,
    haversine_m,
    make_point,
    out_of_china,
    wgs84_to_gcj02,
)

# 境内代表点：重庆解放碑 / 北京 / 上海
CHINA_POINTS = [(106.55, 29.56), (116.40, 39.90), (121.47, 31.23)]
# 境外代表点：巴黎 / 纽约
FOREIGN_POINTS = [(2.35, 48.85), (-74.0, 40.7)]


@pytest.mark.parametrize("lon, lat", CHINA_POINTS)
def test_roundtrip_wgs_to_gcj_to_wgs(lon: float, lat: float) -> None:
    """往返 gcj02_to_wgs84(wgs84_to_gcj02(p)) 与原值误差 < 1e-5 度。"""
    g_lon, g_lat = wgs84_to_gcj02(lon, lat)
    w_lon, w_lat = gcj02_to_wgs84(g_lon, g_lat)
    assert abs(w_lon - lon) < 1e-5
    assert abs(w_lat - lat) < 1e-5


@pytest.mark.parametrize("lon, lat", CHINA_POINTS)
def test_inland_offset_100_to_1000m(lon: float, lat: float) -> None:
    """境内偏移量应在 100~1000 米（典型 400-700m）。"""
    g_lon, g_lat = wgs84_to_gcj02(lon, lat)
    offset = haversine_m(lon, lat, g_lon, g_lat)
    assert 100.0 < offset < 1000.0


@pytest.mark.parametrize("lon, lat", FOREIGN_POINTS)
def test_foreign_identity(lon: float, lat: float) -> None:
    """境外直通：转换前后完全相等（恒等）。"""
    assert wgs84_to_gcj02(lon, lat) == (lon, lat)
    assert gcj02_to_wgs84(lon, lat) == (lon, lat)


def test_out_of_china_flag() -> None:
    """境内 False、境外 True。"""
    assert out_of_china(106.55, 29.56) is False
    assert out_of_china(116.40, 39.90) is False
    assert out_of_china(2.35, 48.85) is True
    assert out_of_china(-74.0, 40.7) is True


def test_make_point() -> None:
    """make_point 返回 SRID 4326 的 WKTElement，WKT 顺序为 lon lat。"""
    pt = make_point(106.55, 29.56)
    assert isinstance(pt, WKTElement)
    assert pt.srid == 4326
    wkt = str(pt)
    assert "POINT(" in wkt
    nums = re.findall(r"-?\d+\.?\d*", wkt.split("(", 1)[1].rstrip(")"))
    assert len(nums) == 2
    assert float(nums[0]) == pytest.approx(106.55)
    assert float(nums[1]) == pytest.approx(29.56)


def test_haversine_beijing_to_shanghai() -> None:
    """北京→上海 ≈ 1067km（±60km 容差）。"""
    d = haversine_m(116.40, 39.90, 121.47, 31.23)
    assert abs(d - 1_067_000.0) < 60_000.0


def test_haversine_zero_and_symmetry() -> None:
    """零距离=0；对称性 |d(a,b)-d(b,a)|<1e-6。"""
    assert haversine_m(106.55, 29.56, 106.55, 29.56) == 0.0
    d_ab = haversine_m(106.55, 29.56, 116.40, 39.90)
    d_ba = haversine_m(116.40, 39.90, 106.55, 29.56)
    assert abs(d_ab - d_ba) < 1e-6


def test_zero_coords_no_crash() -> None:
    """极端输入 (0,0)：判境外、转换恒等、不炸。"""
    assert out_of_china(0.0, 0.0) is True
    assert wgs84_to_gcj02(0.0, 0.0) == (0.0, 0.0)
    assert gcj02_to_wgs84(0.0, 0.0) == (0.0, 0.0)
