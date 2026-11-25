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

R41（2026-11-25 用户令「附近餐厅都没有被推荐插入到餐卡。除了 RATE,
GEOGRAPHIC. 还考虑一下 RATING NUMBER.」）把选择口径升级为
**「评分 × 评分数（可信度）× 距离」打分 + 地理簇配额**：

- 旧版按「锚点下标升序」每桶取 1 家、全程上限 4——真实库实测 4 个名额全落
  在市中心簇（同一天最多用 2 家），后面的天一家候选都没有；同一批锚点倒序
  传入入选 4 家全换（结果由锚点顺序决定而非质量/距离）。
- 旧版评分数只作并列次序键：5.0 分 1 条评论压过 4.9 分 648 条评论。
- 新版先按贝叶斯可信度折评分（`credible_rating`），再减去距离折价
  （`MEAL_GEO_KM_PENALTY` 评分点/km）得总分；锚点按 2.5km 单链聚成「可同日
  簇」，逐簇轮换取前 `per_cluster` 家（午/晚各一家量级），全池上限 `limit`
  由调用方按行程天数给（午晚双槽）。每簇都有名额后才给某簇第二家，名额不再
  被排在前面的市中心簇吃光。

本模块只做**纯函数**选择：给定候选行（两表同形状）+ 锚点（景点坐标），
按可信度评分与到最近锚点的距离选人、按簇配额截断。
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
# 每个「可同日簇」按总分取前 N（同日午/晚双槽各一家就够，多了稀释模型）。
MEAL_GEO_PER_CLUSTER = 2
# 全池默认上限（CP-SAT 模型规模护栏：候选数直接进 pairwise 走行矩阵）。
# 调用方按行程天数覆盖（2×天数，4 天=8）。
MEAL_GEO_LIMIT = 8
# 评分闸：无评分行不进 geo 池（「按评分选」的前提；名录骨架行仍可由
# top_pois 的老路径进池，行为不变）。
MEAL_GEO_MIN_RATING = 4.0
# 锚点聚簇半径（单链）：簇内景点地理上可同一天逛完，共享餐厅配额。
# 与引擎侧就近闸 objectives/c09 的 MEAL_NEAR_SIGHT_KM=2.5 同口径。
MEAL_GEO_CLUSTER_KM = 2.5
# R41 评分数先验权重 C：评论数中位数量级（2026-11-25 真库审计：北京 ≥4.0 行
# 评分数 Q1=8 / 中位=22 / Q3=60）。n=C 时自身评分与先验各占一半。
MEAL_GEO_RATING_PRIOR_WEIGHT = 20.0
# R41 距离折价：每多 1km 扣 0.25 个评分点——「4.5 分隔壁店」约等于
# 「4.9 分 1.8km 外」，距离从此真实参与排序而不是只做最后的并列键。
MEAL_GEO_KM_PENALTY = 0.25
#: R41c 最小样本量：评分数（评论条数）低于此值的行不进自动推荐（2026-11-25
#: 用户「D1 怎么会选一个只有一条评论的餐厅」）。可信度折后评分对小样本本来
#: 就按先验计，但没有竞争对手时这种行仍会被选中（颐和园/圆明园 2km 内只有
#: 一家 5.0×1 条的店）——宁留「自由安排」占位，也不拿一条点评充数。
#: 取 10 而不是 50：审计显示 n≥50 会把什刹海/鸟巢各饿到只剩 1 家、圆明园 0 家。
MEAL_GEO_MIN_COUNT = 10

# R38（2026-11-25 用户「北京璞瑄酒店·大堂吧既不是娱乐也不是酒店也不是
# 餐厅 / 当作餐厅为什么后面还有一个晚餐自由卡」）：酒廊 / 大堂吧 / 酒吧
# 不是正餐餐厅，即便评分高、离景点近也不得占命名午餐/晚餐卡。R29 把
# restaurants 表每一行都投影成 category="food"，导致「大堂吧」这类行靠
# TA 满分挤进 geo 池、顶掉真餐馆，当天晚餐又落回「晚饭（自由安排）」。
# 这里按菜系组 + 名称标记把非正餐行挡在 geo 池外——原行留库不动，
# top_pois 老路径与下午茶语义零影响。
_NON_MEAL_CUISINE_GROUPS = frozenset({"酒吧夜店"})
_NON_MEAL_NAME_MARKERS = ("大堂吧", "酒廊", "lobby lounge", "lobby bar", "酒吧")
#: 反向标记（2026-11-25 库审）：名字里明说是餐厅的（「Calypso地中海餐厅·
#: 酒廊」= 餐厅附带酒廊，库里菜系组是西餐）不按上面标记剔——剔了只会让
#: 餐池更空（用户紧接着问的「why no restaurants is picked up at all」）。
_MEAL_NAME_MARKERS = ("餐厅", "restaurant", "食府", "食堂")


def is_non_meal_venue(row: dict[str, Any]) -> bool:
    """酒廊/大堂吧/酒吧类非正餐餐饮行判定（纯函数）。

    只看菜系组与名称标记，不动评分/坐标/来源；缺字段的行不误伤。
    名字里明说「餐厅」的先行放行（库审：「源膳全日餐厅」「古城老院餐厅」
    的菜系组被标成酒吧夜店，按组剔会白让掉两家真馆子）。
    """
    name = _norm_cuisine(str(row.get("name") or ""))
    if name and any(_norm_cuisine(m) in name for m in _MEAL_NAME_MARKERS):
        return False
    for key in ("cuisine_group", "cuisine", "cuisine_family"):
        value = str(row.get(key) or "")
        if value and _norm_cuisine(value) in _NON_MEAL_CUISINE_GROUPS:
            return True
    if not name:
        return False
    return any(_norm_cuisine(m) in name for m in _NON_MEAL_NAME_MARKERS)


def _norm_cuisine(s: str) -> str:
    return "".join(s.split()).lower()


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


def credible_rating(
    row: dict[str, Any], *, prior: float = MEAL_GEO_MIN_RATING
) -> float:
    """R41 贝叶斯可信度评分＝(C·prior + n·rating) / (C + n)。

    - 评分数 n 是评分的样本量：n 越大折后评分越接近原始评分，n=0（无评论
      数）只能按先验计——「5.0 分 1 条评论」不再压过「4.9 分 648 条评论」。
    - 先验取评分闸 4.0 而不是语料均值（审计值 4.38）：保证折后分 ≤ 原始分、
      且对评分与评分数都单调不减——不会出现「低分少评论的行被先验抬高、
      压过高分多评论的行」。
    - 无评分行返回 0.0（不进 geo 池；质量分也不得因此拿满分）。
    """
    rating = rating_of(row)
    if rating <= 0:
        return 0.0
    n = max(0, _count_of(row))
    c = MEAL_GEO_RATING_PRIOR_WEIGHT
    return (c * prior + n * rating) / (c + n)


def quality_score(row: dict[str, Any]) -> int:
    """R41 餐候选的库内数据质量分（0-100 域，与 live._data_priority_score 同域）。

    吃可信度评分而不是原始评分（评分数进模型）；无评分行 = 0——旧版
    `_data_priority_score` 的 `max(1, …)` 地板值会让无评分餐厅落进 float 域
    ×100 拿满质量奖励（实盘：无评分的白家大院质量奖励 +100，比 4.9 分 648 条
    评论的店还高）。
    """
    adj = credible_rating(row)
    if adj <= 0:
        return 0
    return int(round(adj * 10))


def _name_key(row: dict[str, Any]) -> str:
    return re.sub(r"\s+", "", str(row.get("name") or "")).lower()


def _anchor_clusters(
    pts: Sequence[tuple[float, float]], cluster_km: float
) -> list[int]:
    """锚点单链聚簇（≤cluster_km 即同簇），返回每个锚点的簇 id（最小下标）。

    簇=地理上可以同一天逛完的一组景点；餐厅配额按簇给，而不是按锚点下标
    给——否则市中心 4 个景点会把全程 4 个名额吃光（R41 实测）。
    """
    parent = list(range(len(pts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if (
                haversine_m(pts[i][0], pts[i][1], pts[j][0], pts[j][1]) / 1000.0
                > cluster_km
            ):
                continue
            pi, pj = find(i), find(j)
            if pi != pj:
                parent[max(pi, pj)] = min(pi, pj)
    return [find(i) for i in range(len(pts))]


def thin_evidence_nearby(
    rows: Iterable[dict[str, Any]],
    anchors: Sequence[tuple[float, float]],
    *,
    radius_km: float = MEAL_GEO_RADIUS_KM,
    min_rating: float = MEAL_GEO_MIN_RATING,
    min_count: int = MEAL_GEO_MIN_COUNT,
) -> list[str]:
    """半径内「评分达标但评论数不足」的店名（披露为什么没给这家卡推荐）。

    与 `select_geo_rated` 同一套闸，只把评分数闸反过来取——用于出站披露：
    「附近 2km 内只有评论数不足的餐馆，未自动推荐」。
    """
    pts = [
        (float(a[0]), float(a[1]))
        for a in (anchors or ())
        if isinstance(a, (tuple, list)) and len(a) >= 2
    ]
    if not rows or not pts:
        return []
    out: list[str] = []
    for row in rows:
        if is_non_meal_venue(row):
            continue
        coords = _coords(row)
        rating = rating_of(row)
        if coords is None or rating < min_rating:
            continue
        if _count_of(row) >= max(0, min_count):
            continue
        dists = [haversine_m(coords[0], coords[1], p[0], p[1]) / 1000.0 for p in pts]
        if min(dists) > radius_km:
            continue
        name = str(row.get("name") or "")
        if name and name not in out:
            out.append(name)
    return out


def select_geo_rated(
    rows: Iterable[dict[str, Any]],
    anchors: Sequence[tuple[float, float]],
    *,
    radius_km: float = MEAL_GEO_RADIUS_KM,
    per_cluster: int = MEAL_GEO_PER_CLUSTER,
    limit: int = MEAL_GEO_LIMIT,
    min_rating: float = MEAL_GEO_MIN_RATING,
    min_count: int = MEAL_GEO_MIN_COUNT,
    cluster_km: float = MEAL_GEO_CLUSTER_KM,
) -> list[dict[str, Any]]:
    """按「可信度评分 × 距离」+ 地理簇配额选餐候选（纯函数，确定性）。

    规则：
    1. 无坐标 / 无评分（< min_rating）/ 评分数 < min_count（小样本不推荐）/
       距所有锚点 > radius_km 的行不选；
    2. 每行归到**最近**的锚点，锚点再按 cluster_km 聚成可同日簇；
    3. 行总分 = `credible_rating`（评分 × 评分数）− 距离×MEAL_GEO_KM_PENALTY；
       同名行只留总分最高的一条（跨源重复）；
    4. 簇优先级 = 簇内最小锚点下标（调用方把必去排在锚点表前 → 必去所在簇
       优先），逐簇**轮转**取前 per_cluster 家——每簇先各拿 1 家，再有人拿
       第 2 家；若此后仍不足 limit（有货的簇太少），余量按总分补足，
       总数截断到 limit。

    锚点=当日景点集群（legacy `_meal_search_anchor` 同语义）。
    无锚点/无行 → []（调用方保持旧池，零行为变化）。
    """
    pts = [
        (float(a[0]), float(a[1]))
        for a in (anchors or ())
        if isinstance(a, (tuple, list)) and len(a) >= 2
    ]
    if not rows or not pts or limit <= 0:
        return []
    cluster_of = _anchor_clusters(pts, cluster_km)
    # (总分, 折后评分, 评分数, 距离, 簇, 锚点下标, 名键, 行)
    best_by_name: dict[str, tuple] = {}
    for row in rows:
        # R38：酒廊/大堂吧/酒吧不是正餐，先于评分闸剔除（满分大堂吧不得
        # 顶掉真餐馆、留下「晚餐自由安排」占位）。
        if is_non_meal_venue(row):
            continue
        coords = _coords(row)
        rating = rating_of(row)
        if coords is None or rating < min_rating:
            continue
        if _count_of(row) < max(0, min_count):
            continue
        dists = [haversine_m(coords[0], coords[1], p[0], p[1]) / 1000.0 for p in pts]
        idx = min(range(len(dists)), key=lambda i: dists[i])
        if dists[idx] > radius_km:
            continue
        key = _name_key(row)
        if not key:
            continue
        adj = credible_rating(row, prior=min_rating)
        score = adj - MEAL_GEO_KM_PENALTY * dists[idx]
        cand = (score, adj, _count_of(row), dists[idx], cluster_of[idx], idx, key, row)
        prev = best_by_name.get(key)
        if prev is None or (cand[0], cand[2], -cand[3]) > (prev[0], prev[2], -prev[3]):
            best_by_name[key] = cand

    buckets: dict[int, list[tuple]] = {}
    for cand in best_by_name.values():
        buckets.setdefault(cand[4], []).append(cand)
    order = sorted(buckets, key=lambda cl: min(c[5] for c in buckets[cl]))
    for cl in order:
        buckets[cl].sort(key=lambda c: (-c[0], c[3], -c[2], c[6]))

    chosen: list[tuple] = []
    for round_no in range(max(0, per_cluster)):
        for cl in order:
            bucket = buckets[cl]
            if round_no < len(bucket):
                chosen.append(bucket[round_no])
                if len(chosen) >= limit:
                    return [c[7] for c in chosen[:limit]]
    if len(chosen) < limit:
        # 簇配额是**公平底线**而不是硬顶：有货的簇不够多（远郊天本来就没
        # 餐厅、部分簇 2km 内无合格行）时，剩余名额按总分补给最好的候选，
        # 不让全池上限空转（实测只按簇硬顶时 8 个名额只选出 4 家）。
        seen = {c[6] for c in chosen}
        rest = [c for cl in order for c in buckets[cl] if c[6] not in seen]
        rest.sort(key=lambda c: (-c[0], c[3], -c[2], c[6]))
        chosen.extend(rest[: limit - len(chosen)])
    return [c[7] for c in chosen[:limit]]
