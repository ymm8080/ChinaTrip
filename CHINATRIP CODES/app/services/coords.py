"""WGS84 <-> GCJ-02 <-> BD-09 坐标转换（火星坐标系/百度坐标系）。

底库导入铁律（DESIGN/feature_gap_and_dev_plan_2026-10-23.md §4.2）：
外部源（ChinaTravel/OSM 等）坐标为 WGS84，`pois.location` 统一存
GCJ-02（高德系），`wgs84_location` 存原始 WGS84。转换偏移典型
400-700m，仅中国境内有效；境外原样返回。

BD-09 一对（2026-10-27 接入百度 WebService 用）：库存坐标仍是
GCJ-02 不动，换算收敛在 BaiduClient 边界内——标准公开换算式
（百度官方未开放精确公式，此为业界通用实现），往返误差 ~1e-6 度
（亚米级），对步行路线/POI 展示无影响。
"""

from __future__ import annotations

import math

from geoalchemy2.elements import WKTElement

_PI = math.pi
_A = 6378245.0  # 克拉索夫斯基椭球长半轴
_EE = 0.00669342162296594323  # 第一偏心率平方


def out_of_china(lon: float, lat: float) -> bool:
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = (
        -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (
        (160.0 * math.sin(y / 12.0 * _PI) + 320.0 * math.sin(y * _PI / 30.0))
        * 2.0
        / 3.0
    )
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (
        (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI))
        * 2.0
        / 3.0
    )
    return ret


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    if out_of_china(lon, lat):
        return lon, lat
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    """迭代逆推，两轮收敛精度 ~1m，满足 POI 级配准。"""
    if out_of_china(lon, lat):
        return lon, lat
    wgs_lon, wgs_lat = lon, lat
    for _ in range(2):
        g_lon, g_lat = wgs84_to_gcj02(wgs_lon, wgs_lat)
        wgs_lon += lon - g_lon
        wgs_lat += lat - g_lat
    return wgs_lon, wgs_lat


_X_PI = math.pi * 3000.0 / 180.0


def gcj02_to_bd09(lon: float, lat: float) -> tuple[float, float]:
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * _X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    x, y = lon - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def make_point(lon: float, lat: float) -> WKTElement:
    """(lon, lat) -> geography POINT(4326)，赋给 pois/restaurants.location。"""
    return WKTElement(f"POINT({lon!r} {lat!r})", srid=4326)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """两点球面距离（米），匹配阈值判断用。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
