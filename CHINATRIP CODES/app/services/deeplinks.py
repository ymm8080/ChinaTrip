# -*- coding: utf-8 -*-
"""出行 deeplink 组装（设计 v2.2 §6.13 入户五模式导航×出行/自驾）。
铁律 22：只 handoff 不代客交易——产物仅为跳转链接，不代叫车、不碰资金。
全部链接无 key：高德/百度 Web 服务 key 只在后端代理用，永不进客户端。
纯函数模块：零网络、零第三方依赖（仅标准库）。

Vendor 切换（2026-10-28 拍板：一键切图商）：``compose_deeplink(provider=...)``
"amap"（默认，amapuri:// 系）/ "baidu"（baidumap:// 系，坐标序 lat,lng、
coord_type=gcj02）。调用方传 ``settings.map_provider``。百度无公开打车
scheme——taxi 档降级为驾车路线承接（App/网页一致），产品语义不变。
"""

import math
from urllib.parse import quote

__all__ = ["compose_deeplink"]

_MODES = ("taxi", "driving")

_PROVIDERS = ("amap", "baidu")

# 中国范围（境外坐标交给图商没有意义）
_LON_MIN, _LON_MAX = 73.0, 136.0
_LAT_MIN, _LAT_MAX = 3.0, 54.0

_SOURCE = "chinatrip"


def _amap_nav_url(
    name_enc: str,
    lon: float,
    lat: float,
    origin: tuple[str, str, float, float] | None = None,
) -> str:
    """高德网页导航。from=/to= 位置制解析：坐标在前、名称最后。"""
    from_part = ""
    if origin is not None:
        from_part = f"from={origin[2]},{origin[3]},{origin[1]}&"
    return (
        f"https://uri.amap.com/navigation"
        f"?{from_part}to={lon},{lat},{name_enc}&mode=car&coordinate=gaode&callnative=1"
    )


def _b_latlng(lon: float, lat: float) -> str:
    """百度坐标序 lat,lng（与 baidu_client._latlng 同序，切 vendor 不换序）。"""
    return f"{lat},{lon}"


def _baidu_direction_app(
    name_enc: str,
    lon: float,
    lat: float,
    origin: tuple[str, str, float, float] | None = None,
) -> str:
    """百度地图客户端路线调起：baidumap://map/direction。origin 缺省由客户端定位。"""
    origin_part = ""
    if origin is not None:
        origin_part = f"origin={_b_latlng(origin[2], origin[3])}:{origin[0]}&"
    return (
        f"baidumap://map/direction?{origin_part}"
        f"destination={_b_latlng(lon, lat)}:{name_enc}"
        f"&mode=driving&coord_type=gcj02&src={_SOURCE}"
    )


def _baidu_direction_web(
    name_enc: str,
    lon: float,
    lat: float,
    origin: tuple[str, str, float, float] | None = None,
) -> str:
    """百度网页版路线：坐标起终点不需要 region（region 仅地名消歧用）。"""
    origin_part = ""
    if origin is not None:
        origin_part = f"origin={_b_latlng(origin[2], origin[3])}:{origin[0]}&"
    return (
        f"https://api.map.baidu.com/direction?{origin_part}"
        f"destination={_b_latlng(lon, lat)}:{name_enc}"
        f"&mode=driving&coord_type=gcj02&output=html&src={_SOURCE}"
    )


def _enc(name: str) -> str:
    """query 尾参里的中文名必须整体 URL 编码。"""
    return quote(name, safe="")


def _validate(
    mode: str,
    dest_name: str,
    dest_lon: float,
    dest_lat: float,
    origin: tuple[str, float, float] | None = None,
) -> tuple[str, float, float] | None:
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")
    if not isinstance(dest_lon, (int, float)) or not math.isfinite(dest_lon):
        raise ValueError(f"dest_lon must be a finite number, got {dest_lon!r}")
    if not isinstance(dest_lat, (int, float)) or not math.isfinite(dest_lat):
        raise ValueError(f"dest_lat must be a finite number, got {dest_lat!r}")
    if not (_LON_MIN <= dest_lon <= _LON_MAX):
        raise ValueError(
            f"dest_lon {dest_lon} out of China range [{_LON_MIN}, {_LON_MAX}]"
        )
    if not (_LAT_MIN <= dest_lat <= _LAT_MAX):
        raise ValueError(
            f"dest_lat {dest_lat} out of China range [{_LAT_MIN}, {_LAT_MAX}]"
        )
    if not dest_name or not dest_name.strip():
        raise ValueError("dest_name must be a non-empty string")
    if origin is None:
        return None
    oname, olon, olat = origin
    if not isinstance(olon, (int, float)) or not math.isfinite(olon):
        raise ValueError(f"origin_lon must be a finite number, got {olon!r}")
    if not isinstance(olat, (int, float)) or not math.isfinite(olat):
        raise ValueError(f"origin_lat must be a finite number, got {olat!r}")
    if not (_LON_MIN <= olon <= _LON_MAX) or not (_LAT_MIN <= olat <= _LAT_MAX):
        raise ValueError(f"origin ({olon}, {olat}) out of China range")
    if not isinstance(oname, str) or not oname.strip():
        raise ValueError("origin_name must be a non-empty string")
    return oname, olon, olat


def compose_deeplink(
    mode: str,
    dest_name: str,
    dest_lon: float,
    dest_lat: float,
    origin: tuple[str, float, float] | None = None,
    provider: str = "amap",
) -> dict:
    """组装出租/自驾 deeplink（起终点预填，纯链接 handoff）。

    高德惯例：经度在前（dlon 在 dlat 前）；百度 lat,lng。起点缺省时不带
    from=/origin，由图商侧用自身定位。``provider`` 传 ``settings.map_provider``
    （2026-10-28 一键切图商）；缺省 "amap" 保持既有 wire 不变。
    """
    if provider not in _PROVIDERS:
        raise ValueError(f"provider must be one of {_PROVIDERS}, got {provider!r}")
    origin = _validate(mode, dest_name, dest_lon, dest_lat, origin)
    name = _enc(dest_name)
    lon, lat = dest_lon, dest_lat

    if provider == "baidu":
        # 百度无公开打车 scheme：taxi 档同样用驾车路线承接（App 与网页一致）。
        app_origin = None
        web_origin = None
        if origin is not None:
            oname, olon, olat = origin
            olon, olat = round(olon, 6), round(olat, 6)  # 截 6 位（~0.1m），URL/QR 更短
            app_origin = (oname, _enc(oname), olon, olat)
            web_origin = (oname, _enc(oname), olon, olat)
        return {
            "mode": mode,
            "app_deeplink": _baidu_direction_app(name, lon, lat, app_origin),
            "web_fallback": _baidu_direction_web(name, lon, lat, web_origin),
            "source": _SOURCE,
            "provider": provider,
        }

    s_params = ""
    web_origin = None
    if origin is not None:
        oname, olon, olat = origin
        olon, olat = round(olon, 6), round(olat, 6)  # 截 6 位（~0.1m），URL/QR 更短
        s_params = f"slon={olon}&slat={olat}&sname={_enc(oname)}&"
        web_origin = (oname, _enc(oname), olon, olat)

    if mode == "taxi":
        return {
            "mode": "taxi",
            "app_deeplink": f"amapuri://drive/taxi/?{s_params}dlon={lon}&dlat={lat}&dname={name}",
            # 滴滴版 H5(webapp/driverDepart)已 404；网页无法叫车，
            # 退高德路线页（叫车走 App deeplink）。
            "web_fallback": _amap_nav_url(name, lon, lat, web_origin),
            "source": _SOURCE,
            "provider": provider,
        }

    return {
        "mode": "driving",
        "app_deeplink": (
            f"amapuri://route/plan/?sourceApplication={_SOURCE}"
            f"&{s_params}dlon={lon}&dlat={lat}&dname={name}&dev=0&t=0"
        ),
        "web_fallback": _amap_nav_url(name, lon, lat, web_origin),
        "ios_alternative": (
            f"https://maps.apple.com/?dname={name}&dlat={lat}&dlon={lon}&dirflg=r"
        ),
        "source": _SOURCE,
        "provider": provider,
    }
