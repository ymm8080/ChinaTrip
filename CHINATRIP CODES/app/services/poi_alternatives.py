"""同级备选装配（2026-11-05 拍板「每个点要有一个备选，尤其是 UNESCO /
5A / 国际旅行网站推荐」）。

规则唯一定义点（用户拍板三条硬规则 + 落地细则）：

- 同级（SAME LEVEL）：名录档号一致（hit_tier 口径 0=unesco 1=5a 2=国际
  旅行网站 3=国际平台 4=短视频 5=小红书 6=街区 7=风景名胜 8=4A 9=3A
  10=未分层）；档 4/5 同属社媒推荐并作一档。绝不跨档放宽——UNESCO 换
  UNESCO、5A 换 5A、TA 榜换 TA 榜。
- 同类（SAME CATEGORY）：受控类别（normalize_category）精确一致；不足
  时放宽到类别组（文博/展馆、自然/园林、游乐、人文古迹），层级永不放宽。
- 同时长（SIMILAR DURATION）：游时 band 内（容差 max(45, 0.5×游时)，封顶
  120 分钟）；无游时数据的候选仅在带内候选不满时垫底补位。
- 落地细则：同城可选（换点必须当天可行）；排除行程内已有站点与全计划
  已挂过的备选（避免两张卡亮同一个备选）；餐位/酒店卡不挂备选；
  距离近者优先（同档同城内直线距离小 = 换点当天动线更稳）。

装配入口 attach_plan_alternatives：api/plan._plan_turn_body 在**深拷贝**
上挂备选（session.plan 本体与持久化会话永不携带展示数据），每城只查
一次候选池（PoiDetailStore.alternatives_pool），任何异常静默降级——
备选是展示糖，绝不能把行程卡拉挂。
"""

from __future__ import annotations

from math import log2

from app.services.itinerary.models import (
    GeoPoint,
    ItineraryPlan,
    PlanAlternative,
    VisitItem,
)
from app.services.itinerary.rules import haversine_km
from app.services.poi_details import _TIER_TAG
from app.services.poi_seed import CATEGORY_MAP, normalize_category

# 备选默认上限：右侧 chip 区放 3 个以内不挤爆站点行（用户拍板「一个
# 备选」为底线，多给 2 个供挑剔场景）
ALT_LIMIT = 3

# 类别组（同类放宽用；层级与时长永不放宽）
CATEGORY_GROUPS: dict[str, set[str]] = {
    "cultural": {
        "historic",
        "temple",
        "church",
        "memorial",
        "ruins",
        "castle",
        "ancient_town",
        "attraction",
        "viewpoint",
    },
    "museum": {"museum", "gallery"},
    "nature": {"nature", "park", "garden"},
    "fun": {"theme_park", "zoo"},
}

# 受控类别全集（poi_seed.CATEGORY_MAP 的目标值）：库行多已是受控值
# （historic/museum/…），归一先直通再走 raw→受控映射
CONTROLLED_CATEGORIES: set[str] = set(CATEGORY_MAP.values())


def _norm_cat(raw: str | None) -> str | None:
    """类别归一：受控值直通，raw 中文/OSM 值走 normalize_category。"""
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if text in CONTROLLED_CATEGORIES:
        return text
    return normalize_category(text)


_FOOD_MARKS = ("food", "餐饮", "美食", "餐厅")


def level_class(tier: int | None) -> int:
    """名录档号 → 层级类（档 4 短视频/5 小红书并作社媒档 4；None=未分层
    按 10 处理）。备选与主点的层级类必须一致。"""
    if tier in (4, 5):
        return 4
    return tier if tier is not None else 10


def _is_food_row(category: str | None) -> bool:
    c = (category or "").strip()
    return any(m in c for m in _FOOD_MARKS)


def _category_group(cat: str | None) -> str | None:
    c = _norm_cat(cat)
    if not c:
        return None
    for g, members in CATEGORY_GROUPS.items():
        if c in members:
            return g
    return None


def _dur_band(duration_minutes: int | None) -> tuple[int, int] | None:
    """同时长 band：容差 = max(45, 0.5×游时) 封顶 120；短游时不低于
    15 分钟下限。None = 主点无游时数据（band 过滤跳过，rank 垫底）。"""
    if not duration_minutes or duration_minutes <= 0:
        return None
    tol = max(45, min(120, round(duration_minutes * 0.5)))
    return (max(15, duration_minutes - tol), duration_minutes + tol)


def _quality(h: dict) -> float:
    rating = h.get("rating") or 0.0
    count = h.get("rating_count") or 0
    return rating * (1 + (log2(1 + count) if count else 0))


def _norm_name(name: str | None) -> str:
    return (name or "").strip().lower()


def pick_alternatives(
    pool: list[dict],
    *,
    category: str | None,
    tier: int | None,
    duration_minutes: int | None,
    exclude_names: set[str] | None = None,
    exclude_pids: set[str] | None = None,
    near: GeoPoint | None = None,
    limit: int = ALT_LIMIT,
) -> list[PlanAlternative]:
    """从同城候选池里按同级·同类·同时长挑备选（规则见模块头）。

    pool 行 = PoiDetailStore.alternatives_pool 的 hit dict（带 `_tier`）。
    返回按 时长贴近 → 类别贴近 → 口碑 → 距离 排序的 PlanAlternative；
    不足 limit 就少给（宁缺勿滥，绝不跨档/跨时长硬凑）。
    """
    exclude_names = exclude_names or set()
    exclude_pids = exclude_pids or set()
    want_level = level_class(tier)
    cur_cat = _norm_cat(category)
    cur_group = _category_group(category)
    want_dur = duration_minutes if duration_minutes and duration_minutes > 0 else None
    band = _dur_band(want_dur)

    def eligible(h: dict) -> bool:
        name = _norm_name(h.get("name"))
        if not name or name in exclude_names:
            return False
        if _is_food_row(h.get("category")):
            return False
        pid = h.get("source_poi_id")
        if pid and pid in exclude_pids:
            return False
        # 同级硬闸：档类不一致直接出局（绝不放宽）
        if level_class(h.get("_tier")) != want_level:
            return False
        return True

    def cat_key(h: dict) -> int:
        # 0=类别精确一致 1=同类别组 2=类别数据缺失（垫底，同组语义）
        c = _norm_cat(h.get("category"))
        if not c or not cur_cat:
            return 2
        if c == cur_cat:
            return 0
        if cur_group and _category_group(h.get("category")) == cur_group:
            return 1
        return 3

    def dur_key(h: dict) -> tuple[int, int]:
        d = h.get("suggested_duration_min")
        try:
            d = int(d) if d else None
        except (TypeError, ValueError):
            d = None
        if d and want_dur:
            return (0, abs(d - want_dur))
        return (1, 0)  # 无游时数据垫底（带外已知游时已在时长闸出局）

    def dist_km(h: dict) -> float | None:
        loc = h.get("location")
        if not near or not loc or not isinstance(loc, (tuple, list)) or len(loc) != 2:
            return None
        try:
            return haversine_km(near, GeoPoint(lon=float(loc[0]), lat=float(loc[1])))
        except (TypeError, ValueError):
            return None

    cands = [h for h in pool if eligible(h)]
    # 同类闸：精确优先，同组补位（层级/时长不动）；类别完全不一致的出局
    cands = [h for h in cands if cat_key(h) <= 1]
    # 同时长闸（硬规则）：带内已知游时优先；带外已知游时直接出局（不同
    # 时长 ≠ 备选）；仅「无游时数据」的候选在带内不满时垫底补位。
    # 主点本身无游时（band=None）时不过滤，全部同级同类放行。
    if band is not None:
        in_band, unknown = [], []
        for h in cands:
            d = h.get("suggested_duration_min")
            try:
                d = int(d) if d else None
            except (TypeError, ValueError):
                d = None
            if d is None:
                unknown.append(h)
            elif band[0] <= d <= band[1]:
                in_band.append(h)
            # 带外已知游时：出局（不放回）
    else:
        in_band, unknown = cands, []

    def rank(h: dict) -> tuple:
        return (
            dur_key(h),
            cat_key(h),
            round(-_quality(h), 3),
            dist_km(h) if dist_km(h) is not None else 9999.0,
        )

    ordered = sorted(in_band, key=rank) + sorted(unknown, key=rank)
    out: list[PlanAlternative] = []
    for h in ordered:
        if len(out) >= limit:
            break
        tier_n = h.get("_tier")
        out.append(
            PlanAlternative(
                name=str(h.get("name") or ""),
                name_en=h.get("name_en"),
                category=_norm_cat(h.get("category")) or h.get("category"),
                tier=tier_n,
                level_tag=_TIER_TAG.get(tier_n) if tier_n is not None else None,
                duration_minutes=h.get("suggested_duration_min"),
                distance_km=dist_km(h),
                rating=(float(h["rating"]) if h.get("rating") else None),
            )
        )
    return out


def attach_plan_alternatives(plan: ItineraryPlan, store: object) -> ItineraryPlan:
    """深拷贝行程并给每个观光 VisitItem 挂同级备选（模块头规则）。

    - 只动拷贝：session.plan 本体/持久化会话不带展示数据；
    - 餐位（soft_pin food）与酒店卡不挂；
    - 每城只查一次候选池；全计划 used_names 去重（两张卡不亮同一备选）；
    - store 不可用/查池失败 → 该城备选静默留空，绝不上抛。
    """
    copy = plan.model_copy(deep=True)
    if store is None:
        return copy
    visits: list[VisitItem] = []
    for day in copy.days:
        for it in day.items:
            if isinstance(it, VisitItem) and not (
                it.soft_pin and it.category == "food"
            ):
                if (it.category or "") == "hotel":
                    continue
                visits.append(it)
    if not visits:
        return copy
    exclude_names: set[str] = set()
    exclude_pids: set[str] = set()
    for v in visits:
        exclude_names.add(_norm_name(v.name))
        exclude_names.add(_norm_name(v.name_en))
        if v.poi_id:
            exclude_pids.add(str(v.poi_id))
    pools: dict[str, list[dict]] = {}
    used_names: set[str] = set()
    for v in visits:
        city = (v.city or "").strip().removesuffix("市")
        if not city:
            continue
        if city not in pools:
            try:
                pools[city] = list(store.alternatives_pool(city))  # type: ignore[attr-defined]
            except Exception:
                pools[city] = []
        try:
            alts = pick_alternatives(
                pools[city],
                category=v.category,
                tier=v.tier,
                duration_minutes=v.duration_minutes,
                exclude_names=exclude_names | used_names,
                exclude_pids=exclude_pids,
                near=v.location,
            )
        except Exception:
            alts = []
        v.alternatives = alts or None
        for a in alts:
            used_names.add(_norm_name(a.name))
            used_names.add(_norm_name(a.name_en))
    return copy
