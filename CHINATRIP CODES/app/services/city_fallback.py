# -*- coding: utf-8 -*-
"""城市回退点注册表（2026-11-04 master backlog P1#1「回退点入库闸」）。

真根因（181 行重庆坐标投毒）：入库 geocoder 解析失败时**静默回退城市
gov 点**（重庆 106.550464,29.563761=渝中区政府/上清寺）——距城心 0km 恒
过 500km 距城闸，远点冲突闸把 400km 外的真点看成「市中心隔壁」永不触发
（金佛山↔大足石刻实测 82.8km）。候选入口三闸（城+坐标+数据，5c7161c）
之外的**第四闸**：

  ① 解析点=城市回退点 → 拒绝入库/不入池（is_city_fallback_point）
  ② 地址同型闸：行地址命中回退地址族（geocoder 失败时把政府驻地地址
     写进行，「渝中区上清寺」系）→ 该地址不可作 geocode 依据
     （is_fallback_address）

注册表只收**多行实测共享精确点**（tmp_unesco/poison_points.txt，11-04
投毒普查 ≥3 行同点聚簇）；单行聚簇与合法市中心 POI 无法区分，宁缺勿错
不注册——发现新回退簇先人工核实再入表。
"""

from __future__ import annotations

import logging

from app.services.coords import haversine_m

logger = logging.getLogger(__name__)

# 城市（裸名，去「市」尾）→ geocoder 城市级回退点 (lon, lat)。
# 来源：tmp_unesco/poison_points.txt（2026-11-04 投毒普查，多行同点聚簇）。
CITY_FALLBACK_POINTS: dict[str, tuple[float, float]] = {
    "重庆": (106.550464, 29.563761),  # 渝中区政府（上清寺），181 行聚簇
    "苏州": (120.586, 31.297301),
    "西安": (108.94, 34.341101),  # 市政府（未央凤城八路），show 批 5 行
    "广州": (113.265, 23.129101),
    "杭州": (120.209, 30.2471),
    "通化": (125.759, 41.6793),
}

# 城市 → 回退地址族标记串：geocoder 解析失败时把政府驻地地址写进行，
# 行地址含该族串 = 地址本身已投毒（backlog #5 地址面，30 行实测），
# 不得作 geocode 依据（geocode 它必然回到回退点）。
CITY_FALLBACK_ADDRESS_TOKENS: dict[str, tuple[str, ...]] = {
    "重庆": ("渝中区上清寺", "人民支路"),
}

# 回退点判定容差（米）：聚簇点为 provider 确定值，重解析微差 <100m；
# 政府驻地与最近真实景点（解放碑等）≥1km，不误伤。
FALLBACK_TOLERANCE_M = 150.0


def bare_city(city: str | None) -> str:
    """裸城市名（去「市」尾），兼容「重庆」「重庆市」两种入库形态。"""
    return (city or "").strip().removesuffix("市")


def is_city_fallback_point(lon, lat, city) -> bool:
    """坐标是否为该城市的 geocoder 回退点（P1#1 第四闸判定）。

    城市未注册/坐标无效 → False（不误伤注册表外的城市）。
    """
    pt = CITY_FALLBACK_POINTS.get(bare_city(city))
    if pt is None:
        # 2026-11-12 补可观测性：未注册城市=无防护面（181 行投毒事故随时
        # 可能在第 7 座城重演），放行但不留痕违反日志铁律——warn 一次让
        # 投毒普查能发现新城市（不拦行：无聚簇证据拒绝会误杀真数据）。
        if (city or "").strip():
            logger.warning(
                "city_fallback: city %s has no fallback-point registry — "
                "poisoned geocoder points pass unchecked",
                city,
            )
        return False
    if lon is None or lat is None:
        return False
    try:
        return haversine_m(float(lon), float(lat), pt[0], pt[1]) <= FALLBACK_TOLERANCE_M
    except (TypeError, ValueError):
        return False


def is_fallback_address(address, city) -> bool:
    """地址是否命中该城市的回退地址族（地址同型闸判定）。"""
    tokens = CITY_FALLBACK_ADDRESS_TOKENS.get(bare_city(city))
    if not tokens:
        # 同坐标面：地址族未注册=地址面无防护，留痕同 is_city_fallback_point。
        if (city or "").strip():
            logger.warning(
                "city_fallback: city %s has no fallback-address registry — "
                "poisoned addresses remain geocodable",
                city,
            )
        return False
    s = str(address or "")
    return any(t in s for t in tokens)
