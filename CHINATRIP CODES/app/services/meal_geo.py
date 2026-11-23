# -*- coding: utf-8 -*-
"""R29 餐厅候选「评分 × 地理」选择（2026-11-24 用户令
「WHY RESTRAINTS ARE NOT PROPOSED BY RATING AND GEO INFORMATION」+
「WE HV RESTRANTS IN BOTH POIS AND RESTRANT TABLES」）。

修复前的实盘形态（取证见 tmp_probe/resto_live_evidence.md、resto_data_audit.md）：
- 引擎候选池的餐厅只有 `pois` 里带国际荐点标的 4 条北京行（top_pois_in_city
  的 rec-tag 豁免），city 级取数、与当日动线无关；
- legacy 只在高德实时检索可用时有候选（生产 PLAN_RESTAURANT_SEARCH_ENABLED
  =false → 零候选），且 rank_by_detour 里评分权重只有 0.1km/分（满分 5.0
  只值 0.5km）；
- 独立餐厅库 `restaurants`（北京 550 行、267 行有 TripAdvisor 评分、
  米其林 67 + 黑珍珠 22）只被读营业时间/菜系，**从不进候选**。
端上后果：长城日晚餐落到 54km 外的市区店、库内无评分的店顶上餐卡。

本模块只做**纯函数**选择：给定候选行（两表同形状）+ 当日锚点（景点坐标），
按评分（主 rating 缺则 ta_rating）与到最近锚点的距离选人、按锚点配额截断。
DB 读取在 `PoiDetailStore.restaurant_rows_in_city`（restaurants 表）与既有
`top_pois_in_city` / `recommendation_food_in_city`（pois 侧）——本模块不碰库。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Sequence

from app.services.coords import haversine_m

# 闸半径：与 legacy restaurants.NORMAL_MEAL_MAX_KM 同口径（8km=城内顺路量级），
# 不另造距离语义。
MEAL_GEO_RADIUS_KM = 2.0
# 每个锚点按评分取前 N（同日午晚双槽各一家就够，多了稀释模型）。
MEAL_GEO_PER_ANCHOR = 1
# 全池上限（CP-SAT 模型规模护栏：候选数直接进 pairwise 走行矩阵）。
MEAL_GEO_LIMIT = 4
# 评分闸：无评分行不进 geo 池（「按评分选」的前提；名录骨架行仍可由
# top_pois 的老路径进池，行为不变）。
MEAL_GEO_MIN_RATING = 4.0


def _coords(row: dict[str, Any]) -> Optional[tuple[float, float]]:
    loc = row.get("location")
    if isinstance(loc, (tuple, list)) and len(loc) >= 2:
        try:
            return float(loc[0]), float(loc[1])
        except (TypeError, ValueError):
            return None
    return None


def rating_of(row: dict[str, Any]) -> float:
    """候选行评分（主 rating 优先；poi_details 已把 ta_rating 折进 rating）。"""
    try:
        return float(row.get("rating") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _count_of(row: dict[str, Any]) -> int:
    try:
        return int(row.get("rating_count") or 0)
    except (TypeError, ValueError):
        return 0


def _name_key(row: dict[str, Any]) -> str:
    return re.sub(r"\s+", "", str(row.get("name") or "")).lower()


def select_geo_rated(
    rows: Iterable[dict[str, Any]],
    anchors: Sequence[tuple[float, float]],
    *,
    radius_km: float = MEAL_GEO_RADIUS_KM,
    per_anchor: int = MEAL_GEO_PER_ANCHOR,
    limit: int = MEAL_GEO_LIMIT,
    min_rating: float = MEAL_GEO_MIN_RATING,
) -> list[dict[str, Any]]:
    """按「评分 × 到最近锚点距离」选餐候选（纯函数，确定性）。

    规则（顺序即优先级）：
    1. 无坐标 / 无评分（< min_rating）/ 距所有锚点 > radius_km 的行不选；
    2. 每行归到**最近**的锚点，同锚点内按（评分降序、评分人数降序、
       距离升序）取前 per_anchor 家；
    3. 同名行只留评分最高的一条（跨源重复），总数截断到 limit。

    锚点=当日景点集群（legacy `_meal_search_anchor` 同语义）。
    无锚点/无行 → []（调用方保持旧池，零行为变化）。
    """
    pts = [
        (float(a[0]), float(a[1]))
        for a in (anchors or ())
        if isinstance(a, (tuple, list)) and len(a) >= 2
    ]
    if not rows or not pts:
        return []
    best_by_name: dict[str, tuple[float, int, float, int, dict[str, Any]]] = {}
    for row in rows:
        coords = _coords(row)
        rating = rating_of(row)
        if coords is None or rating < min_rating:
            continue
        dists = [haversine_m(coords[0], coords[1], p[0], p[1]) / 1000.0 for p in pts]
        idx = min(range(len(dists)), key=lambda i: dists[i])
        if dists[idx] > radius_km:
            continue
        key = _name_key(row)
        if not key:
            continue
        cand = (rating, _count_of(row), dists[idx], idx, row)
        prev = best_by_name.get(key)
        if prev is None or (cand[0], cand[1]) > (prev[0], prev[1]):
            best_by_name[key] = cand

    buckets: dict[int, list[tuple[float, int, float, int, dict[str, Any]]]] = {}
    for cand in best_by_name.values():
        buckets.setdefault(cand[3], []).append(cand)

    out: list[dict[str, Any]] = []
    for idx in sorted(buckets):
        bucket = sorted(
            buckets[idx],
            key=lambda c: (-c[0], -c[1], c[2]),
        )
        out.extend(c[4] for c in bucket[: max(0, per_anchor)])
        if len(out) >= limit:
            break
    return out[: max(0, limit)]
