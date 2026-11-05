"""同级备选装配（2026-11-05 拍板「每个点要有一个备选，尤其是 UNESCO /
5A / 国际旅行网站推荐」）。

规则唯一定义点（用户拍板三条规则 + 落地细则）：

- 同级（SAME LEVEL）：名录档一致。两套档号在此统一——行程条目 tier 是
  选点梯子（plan._source_tier，1=unesco…10=4a 11=其他 6=演出），候选池
  `_tier` 是 hit_tier（0=unesco…9=3a 10=未分层），PLAN_TIER_TO_POOL 换算
  后同档比较。排序口径：**同档优先，缺档近档补位亮牌披露**——名录档在
  单城里常只有一行（青城山—都江堰是成都唯一 unesco 行），硬闸会让「每
  个点都要有备选」落空：同档候选排前，同档不足 limit 时按 |Δ档| 最近
  的近档补位（premium 档带 0-3 内就近 > 跨档带），chip 上亮备选自身档
  牌（UNESCO/5A/国际榜/…），绝不冒充同级。
- 同类（SAME CATEGORY）：受控类别（normalize_category）精确一致；不足
  时放宽到类别组（人文古迹含文博/展馆、自然/园林、游乐），类别完全不
  一致的出局。文博（museum/gallery）并入人文古迹组是 2026-11-06 拍板
  「杜甫草堂的备选应该是武侯祠」实录：库类别不一致（杜甫草堂=museum、
  武侯祠=attraction）不能把经典人文对拆散。
- 遗址类隔离（2026-11-06 拍板「金沙不合适[作杜甫草堂的备选]」）：名称
  带「遗址」的考古遗址行只与同带「遗址」行互为备选，双向硬闸——层级/
  类别/时长同符也不放行；遗址主点无同带遗址候选则宁缺。
- 同时长（SIMILAR DURATION）：游时 band 内（容差 max(45, 0.5×游时)，封顶
  120 分钟）；带外已知游时出局；无游时数据的候选仅垫底补位。主点无游
  时（band=None）不过滤。
- 落地细则：同城可选（换点必须当天可行）；排除行程内已有站点与全计划
  已亮过的备选（避免两张卡亮同一个备选）；餐位/酒店卡不挂备选；演出
  主点（梯档 6）只亮演出备选；距离近者优先（直线距离小 = 换点动线稳）。

装配入口 attach_plan_alternatives：api/plan._plan_turn_body 在**深拷贝**
上挂备选（session.plan 本体与持久化会话永不携带展示数据），每城只查
一次候选池（PoiDetailStore.alternatives_pool），任何异常静默降级——
备选是展示糖，绝不能把行程卡拉挂。
"""

from __future__ import annotations

import re
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

# 选点梯子档号（plan._source_tier）→ 候选池档号（hit_tier）换算表：
# 梯子 6=演出（不在名录序）、11=其他/未分层，映射为 None（演出走 show
# 专项；未分层按池档 10 处理）。
PLAN_TIER_TO_POOL: dict[int, int | None] = {
    1: 0,  # unesco
    2: 1,  # 5a
    3: 2,  # 国际旅行网站（ta/lp/viator/curated）
    4: 3,  # 国际平台
    5: 4,  # 短视频
    6: None,  # 演出（专项，非名录档）
    7: 5,  # 小红书
    8: 6,  # 街区
    9: 7,  # 风景名胜
    10: 8,  # 4a
    11: None,  # 其他/未分层 → 池档 10
}

# 档带（近档补位范围）：premium 名录档 > 社媒档 > 国内名录档 > 未分层。
# 补位先同带内 |Δ档| 最近，同带空了才跨带（chip 亮牌披露）。
LEVEL_BANDS: tuple[frozenset[int], ...] = (
    frozenset({0, 1, 2, 3}),  # premium：unesco/5a/国际旅行网站/国际平台
    frozenset({4, 5}),  # 社媒：短视频/小红书
    frozenset({6, 7, 8, 9}),  # 国内名录：街区/风景名胜/4A/3A
    frozenset({10}),  # 未分层
)

SHOW_LEVEL = "show"  # 演出主点的专项档（梯档 6）

# 类别组（同类放宽用；层级与时长永不放宽）。博物馆/美术馆并入人文古迹
# 组（2026-11-06 拍板「杜甫草堂的备选应该是武侯祠」实录：库类别不一致
# ——杜甫草堂=museum、武侯祠=attraction，分组成墙会把经典人文对拆散）；
# 精确类别在排序中仍优先于组。
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
        "museum",
        "gallery",
    },
    "nature": {"nature", "park", "garden"},
    "fun": {"theme_park", "zoo"},
}

# 遗址类隔离（2026-11-06 拍板「金沙不合适[作杜甫草堂的备选]」实录）：
# 金沙遗址博物馆是考古遗址类，与园林祠庙故居类（杜甫草堂/武侯祠）不是
# 一类东西——名称带「遗址」的行只与同带「遗址」的行互为备选，双向硬闸
# （层级/类别/时长同符也不放行）。遗址主点若无同带遗址候选则宁缺。
RUINS_MARK = "遗址"

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
    """候选池档号（hit_tier）→ 层级类（档 4 短视频/5 小红书并作社媒档
    4；None=未分层按 10 处理）。"""
    if tier in (4, 5):
        return 4
    return tier if tier is not None else 10


def plan_tier_to_pool(tier: int | None) -> int | None | str:
    """行程条目 tier（选点梯子 1..11）→ 候选池档号（0..10）；演出梯档 6
    返回 SHOW_LEVEL；其他/未知（11/None）回 10（池档未分层）。"""
    if tier == 6:
        return SHOW_LEVEL
    mapped = PLAN_TIER_TO_POOL.get(tier)
    if mapped is None:
        return 10
    return mapped


def _band_of(cls: int) -> int:
    return next((i for i, b in enumerate(LEVEL_BANDS) if cls in b), -1)


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
    15 分钟下限。None = 主点无游时数据（band 过滤跳过）。"""
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


# 同体名排除：破折号/间隔号变体（青城山—都江堰 ↔ 青城山-都江堰风景
# 名胜区）先剥，再走 poi_details._name_overlap（头/尾互含）+ 同核包含。
# 同核：剥通用类尾词后短核被长核包含即同体——「都江堰景区」剥尾=都江堰
# ⊂ 青城山都江堰（实录：换过去 alias 解析回同一伞形行，等于没换）；
# 「成都杜甫草堂博物馆」剥尾=成都杜甫草堂 ⊃ 杜甫草堂（多源同馆两行）。
_NAME_STRIP = str.maketrans("", "", "-—–·・ ")
_CORE_TAILS = (
    "风景名胜区",
    "旅游区",
    "旅游度假区",
    "度假区",
    "风景区",
    "景区",
    "历史文化保护区",
    "保护区",
    "遗址公园",
    "森林公园",
    "湿地公园",
    "博物馆",
    "博物院",
    "纪念馆",
    "陈列馆",
    "遗迹馆",
    "遗址馆",
    "公园",
    "古镇",
    "古城",
    "古街",
    "老街",
    "街区",
)


def _name_core(name: str) -> str:
    n = name.strip().lower().translate(_NAME_STRIP)
    changed = True
    while changed:
        changed = False
        for tail in _CORE_TAILS:
            t = tail.translate(_NAME_STRIP)
            if n.endswith(t) and len(n) > len(t) + 1:
                n = n[: -len(t)]
                changed = True
    return n


def _overlap_any(name: str, exclude_names: set[str]) -> bool:
    """候选名与排除名（行程内已有 + 已亮过的备选）同体判定：剥连字符
    变体后，头/尾互含（_name_overlap）或同核包含任一命中即同体。"""
    from app.services.poi_details import _name_overlap

    n = name.translate(_NAME_STRIP)
    if not n:
        return False
    core_n = _name_core(n)
    for ex in exclude_names:
        ex_s = ex.translate(_NAME_STRIP)
        if _name_overlap(n, ex_s):
            return True
        core_ex = _name_core(ex_s)
        # ≥2 字核互含即同体（锦里 ⊂ 武侯祠锦里）；过短单字不认
        if (
            len(core_n) >= 2
            and len(core_ex) >= 2
            and (core_n in core_ex or core_ex in core_n)
        ):
            return True
    return False


# 演出场馆名守卫：类别缺失的剧场/影院行不得当观光点备选（成都文殊坊
# 妙剧场混进动物园备选实录）；演出主点（tier 6）不适用
_SHOW_NAME_PATTERN = "剧场|剧院|演艺|影院|演出中心|音乐厅|秀"

# 短语行守卫：baidu 等源的描述性短语名（「看成都附近的水利工程」实录）
# 不是真点位名——动词开头或带「附近」的一律不候选
_JUNK_NAME_RE = re.compile("^(看|去|逛|游|玩|打卡|体验|参观)|附近")


def _looks_show_name(name: str) -> bool:
    return bool(re.search(_SHOW_NAME_PATTERN, name))


def pick_alternatives(
    pool: list[dict],
    *,
    category: str | None,
    tier: int | None,
    duration_minutes: int | None,
    exclude_names: set[str] | None = None,
    exclude_pids: set[str] | None = None,
    near: GeoPoint | None = None,
    main_name: str | None = None,
    limit: int = ALT_LIMIT,
) -> list[PlanAlternative]:
    """从同城候选池里按同级·同类·同时长挑备选（规则见模块头）。

    tier 收行程条目口径（选点梯子 1..11，plan_tier_to_pool 换算）；pool
    行 = PoiDetailStore.alternatives_pool 的 hit dict（带 `_tier`，hit_tier
    口径）；main_name = 主点名（遗址类隔离闸用）。返回 PlanAlternative：
    同档排前，缺档近档补位（|Δ档| 最近，chip 亮备选自身档牌）；不足
    limit 就少给。
    """
    exclude_names = exclude_names or set()
    exclude_pids = exclude_pids or set()
    want = plan_tier_to_pool(tier)
    is_show = want == SHOW_LEVEL
    want_level = level_class(None if is_show else want)  # show 无池档类
    want_band = -1 if is_show else _band_of(want_level)
    cur_cat = _norm_cat(category)
    cur_group = _category_group(category)
    want_dur = duration_minutes if duration_minutes and duration_minutes > 0 else None
    band = _dur_band(want_dur)
    main_is_ruins = RUINS_MARK in (main_name or "")

    def is_show_row(h: dict) -> bool:
        tags = {str(t).strip().lower() for t in (h.get("tags") or [])}
        return "show" in tags or _norm_cat(h.get("category")) == "entertainment"

    def row_is_ruins(h: dict) -> bool:
        # 遗址类判定：名称带「遗址」（金沙遗址博物馆）；广汉三星堆类名录
        # 行名称无「遗址」二字，简介兜底（intro ≤60 字必提遗址）
        return RUINS_MARK in (h.get("name") or "") or RUINS_MARK in (
            h.get("intro") or ""
        )

    def level_key(h: dict) -> tuple[int, int]:
        # (档惩罚, |Δ档|)：0=同档 1=同带近档 2=跨带；演出主点全档同列
        if is_show:
            return (0, 0)
        cand = level_class(h.get("_tier"))
        if cand == want_level:
            return (0, 0)
        cb = _band_of(cand)
        if cb != -1 and cb == want_band:
            return (1, abs(cand - want_level))
        return (2, abs(cand - want_level))

    def eligible(h: dict) -> bool:
        name = _norm_name(h.get("name"))
        if not name or _overlap_any(name, exclude_names):
            return False
        if _JUNK_NAME_RE.search(name):
            return False  # 描述性短语行（看成都附近的水利工程实录）不是点位
        if _is_food_row(h.get("category")):
            return False
        pid = h.get("source_poi_id")
        if pid and pid in exclude_pids:
            return False
        if is_show:
            return is_show_row(h)
        if is_show_row(h) or _looks_show_name(name):
            return False  # 演出/场馆行不是观光点的备选（含类别缺失行）
        # 遗址类隔离（双向硬闸）：遗址主点只换遗址，非遗址主点不换遗址
        if row_is_ruins(h) != main_is_ruins:
            return False
        return True

    def cat_key(h: dict) -> int:
        # 0=类别精确一致 1=同类别组 3=类别完全不一致（出局）；演出主点
        # 免类别闸（演出同名录外）
        if is_show:
            return 0
        c = _norm_cat(h.get("category"))
        if not c or not cur_cat:
            return 2  # 类别数据缺失：垫底补位语义
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
    # 同类闸：精确/同组/缺失垫底保留，完全不一致的出局
    cands = [h for h in cands if cat_key(h) <= 2]
    # 同时长闸（硬规则）：带内已知游时优先；带外已知游时直接出局；无游
    # 时数据垫底补位。主点无游时（band=None）不过滤。演出主点免闸（游
    # 时无信号常态）。
    if band is not None and not is_show:
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
            level_key(h),  # 同档 > 同带近档 > 跨带（亮牌披露）
            dur_key(h),
            cat_key(h),
            round(-_quality(h), 3),
            dist_km(h) if dist_km(h) is not None else 9999.0,
        )

    ordered = sorted(in_band, key=rank) + sorted(unknown, key=rank)
    out: list[PlanAlternative] = []
    picked_names: set[str] = set()
    for h in ordered:
        if len(out) >= limit:
            break
        # 本条目内去重：多源同馆两行（杜甫草堂 ↔ 成都杜甫草堂博物馆）、
        # 组合行（武侯祠·锦里 ↔ 武侯祠）不重复亮两张同体 chip
        nm = _norm_name(h.get("name"))
        if nm and _overlap_any(nm, picked_names):
            continue
        tier_n = h.get("_tier")
        out.append(
            PlanAlternative(
                name=str(h.get("name") or ""),
                name_en=h.get("name_en"),
                category=_norm_cat(h.get("category")) or h.get("category"),
                tier=tier_n,  # 池档口径（hit_tier），H5 只读 level_tag
                level_tag=_TIER_TAG.get(tier_n) if tier_n is not None else None,
                duration_minutes=h.get("suggested_duration_min"),
                distance_km=dist_km(h),
                rating=(float(h["rating"]) if h.get("rating") else None),
            )
        )
        if nm:
            picked_names.add(nm)
    return out


def _heal_tier(v: VisitItem, store: object) -> None:
    """档号自愈（读路径，只动展示拷贝）：换点端点 2026-11-06 前换入的行
    不带 tier（replace_item 漏设），历史会话按未分层处理会让同级备选全
    落 t10 杂馆（杜甫草堂卡亮失落博物馆实录）——有 poi_id 的行回库按
    _source_tier 同口径重算。失败静默保留原值。"""
    if v.tier is not None or not v.poi_id:
        return
    try:
        row = store.get(str(v.poi_id))  # type: ignore[attr-defined]
        if not row:
            return
        from app.services.agent.plan import _source_tier

        v.tier = _source_tier(row)
    except Exception:
        pass


def attach_plan_alternatives(plan: ItineraryPlan, store: object) -> ItineraryPlan:
    """深拷贝行程并给每个观光 VisitItem 挂同级备选（模块头规则）。

    - 只动拷贝：session.plan 本体/持久化会话不带展示数据；
    - 餐位（food，含 soft_pin 占位）与酒店卡不挂；
    - tier=None 的行按 poi_id 回库自愈档号（历史换点会话）；
    - 每城只查一次候选池；全计划 used_names 去重（两张卡不亮同一备选）；
    - store 不可用/查池失败 → 该城备选静默留空，绝不上抛。
    """
    copy = plan.model_copy(deep=True)
    if store is None:
        return copy
    visits: list[VisitItem] = []
    for day in copy.days:
        for it in day.items:
            if not isinstance(it, VisitItem):
                continue
            cat = (it.category or "").strip()
            if cat in ("food", "hotel") or (it.soft_pin and cat == "food"):
                continue
            _heal_tier(it, store)
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
                main_name=v.name,
            )
        except Exception:
            alts = []
        v.alternatives = alts or None
        for a in alts:
            used_names.add(_norm_name(a.name))
            used_names.add(_norm_name(a.name_en))
    return copy
