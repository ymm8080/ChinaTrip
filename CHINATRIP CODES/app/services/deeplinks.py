# -*- coding: utf-8 -*-
"""出行 deeplink 组装（设计 v2.2 §6.13 入境五模式导航·出租/自驾）。

铁律 22：只 handoff 不代客交易——产物仅为跳转链接，不代叫车、不碰资金。
全部链接无 key：高德 Web 服务 key 只在后端代理用，永不进客户端。
纯函数模块：零网络、零第三方依赖（仅标准库）。
"""

import math
from urllib.parse import quote

__all__ = ["compose_deeplink"]

_MODES = ("taxi", "driving")

# 中国范围（境外坐标交给高德没有意义）
_LON_MIN, _LON_MAX = 73.0, 136.0
_LAT_MIN, _LAT_MAX = 3.0, 54.0

_SOURCE = "chinatrip"


def _enc(name: str) -> str:
    """query 尾参里的中文名必须整体 URL 编码。"""
    return quote(name, safe="")


def _validate(mode: str, dest_name: str, dest_lon: float, dest_lat: float) -> None:
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


def compose_deeplink(
    mode: str, dest_name: str, dest_lon: float, dest_lat: float
) -> dict:
    """组装出租/自驾 deeplink（目的地预填，纯链接 handoff）。

    高德惯例：经度在前（dlon 在 dlat 前）。
    """
    _validate(mode, dest_name, dest_lon, dest_lat)
    name = _enc(dest_name)
    lon, lat = dest_lon, dest_lat

    if mode == "taxi":
        return {
            "mode": "taxi",
            "app_deeplink": f"amapuri://drive/taxi/?dlon={lon}&dlat={lat}&dname={name}",
            "web_fallback": (
                f"https://common.diditaxi.com.cn/webapp/driverDepart/index"
                f"?destLng={lon}&destLat={lat}&destName={name}"
            ),
            "source": _SOURCE,
        }

    return {
        "mode": "driving",
        "app_deeplink": (
            f"amapuri://route/plan/?sourceApplication={_SOURCE}"
            f"&dlon={lon}&dlat={lat}&dname={name}&dev=0&t=0"
        ),
        "web_fallback": (
            f"https://uri.amap.com/navigation"
            f"?to={lon},{lat},{name}&mode=car&coordinate=gaode&callnative=1"
        ),
        "ios_alternative": (
            f"https://maps.apple.com/?dname={name}&dlat={lat}&dlon={lon}&dirflg=r"
        ),
        "source": _SOURCE,
    }
