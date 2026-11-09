"""同级备选装配（2026-11-05 拍板「每个点要有一个备选，尤其是 UNESCO /
5A / 国际旅行网站推荐」）。

规则唯一定义点（用户拍板三条规则 + 落地细则）：

- 同级（SAME LEVEL，2026-11-06 二拍改硬闸）：档带一致。两套档号在此
  统一——行程条目 tier 是选点梯子（plan._source_tier，1=unesco…10=4a
  11=其他 6=演出），候选池 `_tier` 是 hit_tier（0=unesco…9=3a 10=未分
  层），PLAN_TIER_TO_POOL 换算后同带比较。档带（LEVEL_BANDS）：premium
  （unesco/5a/国际旅行网站/国际平台）、社媒（短视频/小红书）、国内名录
  （街区/风景名胜/4A/3A）、未分层——**跨档带候选一律出局，宁缺不滥**
  （5A 主点卡亮 4A 馆实录；首版「近档补位亮牌披露」被用户
  否决：4A 不能作 5A/世遗的替代品）。带内仍按 |Δ档| 就近排序，chip 亮
  备选自身档牌（UNESCO/5A/国际榜/…），绝不冒充同级；带内不足 limit
  就少给，主点备选宁空。
- 同类（SAME CATEGORY）：受控类别（normalize_category）精确一致；不足
  时放宽到类别组；类别完全不一致**或类别缺失**的出局（2026-11-06 二
  拍：同类别是硬规则，缺失无法验证同类就不放行）。组别（2026-11-06
  拍板二改）：
  ①综合观光组 sight = attraction/viewpoint/museum/gallery（园林故居类
  museum↔祠堂类 attraction 仍同组互备）；②人文古迹组 heritage =
  historic/temple/church/memorial/ruins/castle/ancient_town（与观光组
  拆开，祠庙故居遗迹不与泛观光点互备）；③自然/园林 nature；④游乐 fun。
- 遗址类隔离（2026-11-06 拍板「遗址类不合适作园林故居类备选」）：名称/
  简介带「遗址」的考古遗址行只与同带「遗址」行互为备选，双向硬闸——
  层级/类别/时长同符也不放行；遗址主点无同带遗址候选则宁缺。
- CITYWALK 类隔离（2026-11-06 拍板「CITYWALK 单独一组」）：街区压马路
  型点位只与同类互为备选，双向硬闸。判定：功能标签 citywalk > 名录街
  区档（hit_tier 6 / 选点梯子 8）> 名称街巷类词（知名古街类实
  录——标签批打未全覆盖的兜底）。
- 演出经典一组（2026-11-06 拍板「show 是经典一组」）：演出（选点梯档
  6）单独一组——show 主点只亮 show 备选（tags show / entertainment 类），
  show 行不当观光点备选（含剧场/影院/秀名称行），双向硬闸，层级/类别/
  时长免闸（演出同名录外）。
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

import logging
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

logger = logging.getLogger(__name__)

# 备选默认上限：右侧 chip 区放 3 个以内不挤爆站点行（用户拍板「一个
# 备选」为底线，多给 2 个供挑剔场景）
ALT_LIMIT = 3


def _dur_capped(h: dict) -> int | None:
    # 游时读值统一入口（排序/带闸/展示三处同口径）。2026-11-08 二拍：
    # commercial 帽撤除——开场闸（11-07 第五拍）下 240min 可落 13:00-
    # 17:00，压帽与用户「240 肯定能被任何一天放下」终裁相抵。
    d = h.get("suggested_duration_min")
    try:
        d = int(d) if d else None
    except (TypeError, ValueError):
        d = None
    return d


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

# 档带（同级硬闸分界，2026-11-06 二拍）：带内互备，跨带出局宁缺。
# 带内排序：同档 > |Δ档| 最近（chip 亮牌披露）。
LEVEL_BANDS: tuple[frozenset[int], ...] = (
    frozenset({0, 1, 2, 3}),  # premium：unesco/5a/国际旅行网站/国际平台
    frozenset({4, 5}),  # 社媒：短视频/小红书
    frozenset({6, 7, 8, 9}),  # 国内名录：街区/风景名胜/4A/3A
    frozenset({10}),  # 未分层
)

SHOW_LEVEL = "show"  # 演出主点的专项档（梯档 6）

# 类别组（同类放宽用；层级与时长永不放宽）。2026-11-06 拍板二改：
# attraction/viewpoint/museum/gallery 单独成组（综合观光组，园林故居类
# museum↔祠堂类 attraction 仍同组互备）；historic/temple/… 人文古迹组
# 与之拆开——祠庙故居遗迹不再与泛观光点互备。
CATEGORY_GROUPS: dict[str, set[str]] = {
    "sight": {"attraction", "viewpoint", "museum", "gallery"},
    "heritage": {
        "historic",
        "temple",
        "church",
        "memorial",
        "ruins",
        "castle",
        "ancient_town",
    },
    "nature": {"nature", "park", "garden"},
    "fun": {"theme_park", "zoo"},
}

# 遗址类隔离（2026-11-06 拍板「遗址类不合适作园林故居类备选」实录）：
# 考古遗址类行与园林祠庙故居类不是一类东西——名称/简介带「遗址」的
# 行只与同带「遗址」的行互为备选，双向
# 硬闸（层级/类别/时长同符也不放行）。遗址主点若无同带遗址候选则宁缺。
RUINS_MARK = "遗址"

# CITYWALK 类（2026-11-06 拍板「CITYWALK 单独一组」）：街区压马路型点位
# 只与同类互为备选，双向硬闸。判定（任一命中）：①功能标签 citywalk
# （2026-10-29 功能标签批内核）；②名录街区档（hit_tier 6 = 国家级旅游
# 休闲街区 / 选点梯子 8）；③名称含街巷类词（知名古街类实录
# ——tags 批打未全覆盖时的兜底）。只用多字词：单字「坊」会误伤非街区
# 行（含「坊」字的博物馆被误判实录），「巷」同理收成「巷子」。
CITYWALK_TAG = "citywalk"
CITYWALK_NAME_RE = re.compile("步行街|商业街|老街|古街|新街|街区|风情街|巷子")

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


def is_citywalk(
    name: str | None,
    tags: list | None = None,
    *,
    category: str | None = None,
    pool_tier: int | None = None,
    plan_tier: int | None = None,
) -> bool:
    """CITYWALK 类判定（行级，主点/候选共用）：库行类别 citywalk（2026-11-07
    拍板改档：知名街区/商圈片区）> 功能标签 > 名录街区档 >
    名称街巷坊词（模块头 CITYWALK 类注释）。"""
    if (category or "").strip().lower() == CITYWALK_TAG:
        return True
    if CITYWALK_TAG in {str(t).strip().lower() for t in (tags or [])}:
        return True
    if pool_tier == 6 or plan_tier == 8:
        return True
    return bool(CITYWALK_NAME_RE.search(name or ""))


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


# 同体名排除：破折号/间隔号变体（山—堰 ↔ 山-堰风景名胜区类连字符变
# 体）先剥，再走 poi_details._name_overlap（头/尾互含）+ 同核包含。
# 同核：剥通用类尾词后短核被长核包含即同体——短核剥尾后 ⊂ 长核
# （实录：换过去 alias 解析回同一伞形行，等于没换）；
# 多源同馆两行（全称带前缀 ⊃ 简称）同理同体。
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


def _is_subseq(short: str, long: str) -> bool:
    """short 是否为 long 的子序列（保序删字）：秦始皇陵 ⊂ 秦始皇帝陵。"""
    it = iter(long)
    return all(ch in it for ch in short)


def _overlap_any(name: str, exclude_names: set[str]) -> bool:
    """候选名与排除名（行程内已有 + 已亮过的备选）同体判定：剥连字符
    变体后，头/尾互含（_name_overlap）或同核包含任一命中即同体；≥3 字
    核再做子序列同体（2026-11-06 活库探针实录：5A 主点卡亮同实体别名行
    ——插字变体逃过互含/同核包含）。"""
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
        # ≥2 字核互含即同体（短核 ⊂ 长核带前缀名）；过短单字不认
        if (
            len(core_n) >= 2
            and len(core_ex) >= 2
            and (core_n in core_ex or core_ex in core_n)
        ):
            return True
        # ≥3 字核子序列同体（秦始皇陵 ⊂ 秦始皇帝陵）；过短误伤面大不认
        if (
            len(core_n) >= 3
            and len(core_ex) >= 3
            and (_is_subseq(core_n, core_ex) or _is_subseq(core_ex, core_n))
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
    main_citywalk: bool | None = None,
    exclude_same_class: set[str] | None = None,
    limit: int = ALT_LIMIT,
) -> list[PlanAlternative]:
    """从同城候选池里按同级·同类·同时长挑备选（规则见模块头）。

    tier 收行程条目口径（选点梯子 1..11，plan_tier_to_pool 换算）；pool
    行 = PoiDetailStore.alternatives_pool 的 hit dict（带 `_tier`，hit_tier
    口径）；main_name = 主点名（遗址类隔离闸用）；main_citywalk = 主点
    CITYWALK 类标志（None=按主点名/梯档自判，attach 已回库解析时显式传）；
    exclude_same_class = 行程内已有的泛化替代组同档成员名（同城已滤，
    2026-11-07 泛化拍板：已有街区时其它街区不作 chip，点了必撞 duplicate）。
    返回 PlanAlternative：跨档带出局（同级硬闸），带内同档排前、近档按
    |Δ档| 补位（chip 亮备选自身档牌）；带内不足 limit 就少给。
    """
    exclude_names = set(exclude_names or set())
    exclude_pids = exclude_pids or set()
    exclude_same_class = set(exclude_same_class or set())
    # 同体验替代组词素/泛化品类组（2026-11-07 替代组样本案+泛化拍板）与规划
    # 引擎同源，防两处口径漂移
    from app.services.agent.plan import (
        _GENERIC_SUBSTITUTE_GATE_KM,
        _generic_substitute_group,
        _substitute_group,
    )

    mn = _norm_name(main_name)
    if mn:
        # 主点自身自锚进排除集（同体变体闸的对照锚；attach 层本就传全行
        # 程名，这里兜住直调场景——2026-11-06 5A 主点卡亮同实体别名行探针实录）
        exclude_names.add(mn)
    want = plan_tier_to_pool(tier)
    is_show = want == SHOW_LEVEL
    want_level = level_class(None if is_show else want)  # show 无池档类
    want_band = -1 if is_show else _band_of(want_level)
    cur_cat = _norm_cat(category)
    cur_group = _category_group(category)
    want_dur = duration_minutes if duration_minutes and duration_minutes > 0 else None
    band = _dur_band(want_dur)
    main_is_ruins = RUINS_MARK in (main_name or "")
    if main_citywalk is None:
        main_citywalk = is_citywalk(main_name, plan_tier=(None if is_show else tier))

    def is_show_row(h: dict) -> bool:
        tags = {str(t).strip().lower() for t in (h.get("tags") or [])}
        return "show" in tags or _norm_cat(h.get("category")) == "entertainment"

    def row_is_ruins(h: dict) -> bool:
        # 遗址类判定：名称带「遗址」（考古遗址类行）；名录档遗址类
        # 行名称无「遗址」二字，简介兜底（intro ≤60 字必提遗址）
        return RUINS_MARK in (h.get("name") or "") or RUINS_MARK in (
            h.get("intro") or ""
        )

    def level_key(h: dict) -> tuple[int, int]:
        # (档惩罚, |Δ档|)：0=同档 1=同带近档；跨带已在同级硬闸出局。
        # 演出主点全档同列
        if is_show:
            return (0, 0)
        cand = level_class(h.get("_tier"))
        if cand == want_level:
            return (0, 0)
        return (1, abs(cand - want_level))

    def eligible_reason(h: dict) -> str | None:
        """None=合格；否则返回命中的闸名（2026-11-07 强制日志收口：此前
        全模块零日志，谷卡备选缺失无从排查）。"""
        name = _norm_name(h.get("name"))
        if not name:
            return "no_name"
        if _overlap_any(name, exclude_names):
            return "exclude"
        if _JUNK_NAME_RE.search(name):
            return "junk_name"  # 描述性短语行（看成都附近的水利工程实录）不是点位
        if _is_food_row(h.get("category")):
            return "food"
        pid = h.get("source_poi_id")
        if pid and pid in exclude_pids:
            return "poi_id"
        if is_show:
            return None if is_show_row(h) else "not_show"
        if is_show_row(h) or _looks_show_name(name):
            return "show_row"  # 演出/场馆行不是观光点的备选（含类别缺失行）
        # 同级硬闸（2026-11-06 二拍）：跨档带出局——4A 不作 5A/世遗备选
        # （陕西自然博物馆实录）；带内不足就少给，宁缺不滥
        if _band_of(level_class(h.get("_tier"))) != want_band:
            return "band"
        # 遗址类隔离（双向硬闸）：遗址主点只换遗址，非遗址主点不换遗址
        if row_is_ruins(h) != main_is_ruins:
            return "ruins"
        # CITYWALK 类隔离（双向硬闸，2026-11-06 拍板）：街区压马路型只与
        # 街区压马路型互为备选
        if (
            is_citywalk(
                h.get("name"),
                h.get("tags"),
                category=h.get("category"),
                pool_tier=h.get("_tier"),
            )
            != main_citywalk
        ):
            return "citywalk"
        # 同体验替代组隔离（2026-11-07 替代组样本案，单向）：行程里已有替代
        # 组成员（≠主点本人）时组员不作备选亮卡——点了必撞 duplicate；
        # 主点本人是组员时放行（基地卡亮谷 chip = 正当替换路径）
        g_name = _substitute_group(name)
        if g_name is not None:
            for n in exclude_names:
                if n != mn and _substitute_group(n) == g_name:
                    return "substitute"
        # 泛化品类替代组（2026-11-07 泛化拍板「类型+距离」）：行程里已有
        # 同城同档成员（attach 已滤城滤主点本人）时，同档候选不作 chip；
        # >30km 远郊不算同一体验圈（市区街区↔远郊古城 55km 各算一次）
        if exclude_same_class and _generic_substitute_group(h.get("category")):
            loc = h.get("location")
            if near is not None and isinstance(loc, (tuple, list)) and len(loc) == 2:
                try:
                    cand_pt = GeoPoint(lon=float(loc[0]), lat=float(loc[1]))
                    if haversine_km(near, cand_pt) > _GENERIC_SUBSTITUTE_GATE_KM:
                        return None
                except (TypeError, ValueError):
                    pass
            return "substitute"
        return None

    def cat_key(h: dict) -> int:
        # 0=类别精确一致 1=同类别组 3=不一致/缺失（出局）。同类别是硬
        # 规则（2026-11-06 二拍）：候选类别缺失无法验证同类就不放行
        # （连锁餐饮类图商脏行无类别或错类实录）；主点类别缺
        # 失时类别闸不开（同级档带闸兜底）。演出主点免类别闸（演出同
        # 名录外）；CITYWALK 组内跨类别放行（2026-11-06 拍板「CITYWALK
        # 单独一组」——同片区 historic↔attraction 跨类实录）
        if is_show:
            return 0
        # 同体验替代组互认同类（2026-11-07 用户拍板「替代组基地/谷/苑一个
        # 品类」）：组员 zoo/nature/theme_park 跨 CATEGORY_GROUPS 组，组
        # 内互认精确同类——正当替换路径不被品类闸卡死（谷卡亮基地实录，
        # 首改前 zoo≠nature 在此被杀、chip 永不亮）。互斥闸（eligible
        # substitute 闸）已保证亮卡方向无第三成员，不会串组误放。
        _g_main, _g_cand = (
            _substitute_group(mn),
            _substitute_group(_norm_name(h.get("name"))),
        )
        if _g_main is not None and _g_main == _g_cand:
            return 0
        # 泛化品类组互认（2026-11-07 泛化拍板）：同档白名单成员跨类别组
        # 精确同类——同片区 historic↔attraction 类实录在
        # 库行改档后自然归 citywalk 同类，此处兜住改档前的过渡态
        if exclude_same_class and _generic_substitute_group(h.get("category")):
            return 0
        if main_citywalk:
            c = _norm_cat(h.get("category"))
            return 0 if c and c == cur_cat else 1
        c = _norm_cat(h.get("category"))
        if not c:
            return 3
        if not cur_cat:
            return 0
        if c == cur_cat:
            return 0
        if cur_group and _category_group(h.get("category")) == cur_group:
            return 1
        return 3

    def dur_key(h: dict) -> tuple[int, int]:
        d = _dur_capped(h)
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

    drop_counts: dict[str, int] = {}

    def note_drop(h: dict, gate: str, detail: str = "") -> None:
        drop_counts[gate] = drop_counts.get(gate, 0) + 1
        nm = _norm_name(h.get("name")) or "?"
        # 强制日志（2026-11-07）：结构闸出局与替代组成员死于任何闸都逐
        # 条留痕（替代组类 chip 缺失必须可追溯）；例行过滤（已在行程/杂名/
        # 餐行/无坐标行）只计数不刷屏。
        structural = gate in (
            "band",
            "ruins",
            "citywalk",
            "substitute",
            "show_row",
            "not_show",
        )
        if structural or _substitute_group(nm) is not None:
            logger.info(
                "alternatives: drop %s for main %s gate=%s%s",
                nm,
                main_name or "?",
                gate,
                f" ({detail})" if detail else "",
            )

    cands = []
    for h in pool:
        why = eligible_reason(h)
        if why is None:
            cands.append(h)
        else:
            note_drop(h, why)
    # 同类闸：精确/同组保留，不一致与类别缺失出局
    kept = []
    for h in cands:
        if cat_key(h) <= 1:
            kept.append(h)
        else:
            note_drop(h, "category")
    cands = kept
    # 同时长闸（硬规则）：带内已知游时优先；带外已知游时直接出局；无游
    # 时数据垫底补位。主点无游时（band=None）不过滤。演出主点免闸（游
    # 时无信号常态）。
    if band is not None and not is_show:
        in_band, unknown = [], []
        for h in cands:
            d = _dur_capped(h)
            if d is None:
                unknown.append(h)
            elif band[0] <= d <= band[1]:
                in_band.append(h)
            else:  # 带外已知游时：出局（不放回）
                note_drop(h, "duration", f"d={d}")
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
        # 本条目内去重：多源同馆两行（简称 ↔ 全称带前缀）、
        # 组合行（组合名 ↔ 组合内主站名）不重复亮两张同体 chip
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
                duration_minutes=_dur_capped(h),
                distance_km=dist_km(h),
                rating=(float(h["rating"]) if h.get("rating") else None),
            )
        )
        if nm:
            picked_names.add(nm)
    logger.info(
        "alternatives: main=%s pool=%d picked=%d drops=%s",
        main_name or "?",
        len(pool),
        len(out),
        dict(sorted(drop_counts.items())),
    )
    return out


def _main_row(v: VisitItem, store: object) -> dict | None:
    """主点完整库行（回库一次，档号自愈与 CITYWALK 类判定共用）。

    用 candidate_by_name（全量候选形，含 tags/source/rating）而不是
    store.get——后者是 EN 展示增补 getter，无 tags/source，喂给
    _source_tier 会把名录档行错判成未分层（园林故居类 t2 curated 行
    自愈成 11 实录）。失败静默。"""
    try:
        return store.candidate_by_name(  # type: ignore[attr-defined]
            (v.city or "").strip() or None, v.name
        )
    except Exception:
        logger.warning(
            "alternatives: main row lookup failed for %s (city=%s)",
            v.name,
            v.city,
            exc_info=True,
        )
        return None


def _heal_tier(v: VisitItem, row: dict | None) -> None:
    """档号自愈（读路径，只动展示拷贝）：换点端点 2026-11-06 前换入的行
    不带 tier（replace_item 漏设），历史会话按未分层处理会让同级备选全
    落 t10 杂馆（高 tier 主点卡亮 t10 杂馆实录）——有库行时按
    _source_tier 同口径重算。失败静默保留原值。"""
    if v.tier is not None or not row:
        return
    try:
        from app.services.agent.plan import _source_tier

        v.tier = _source_tier(row)
    except Exception:
        logger.warning(
            "alternatives: tier heal failed for %s (keep tier=%s)",
            v.name,
            v.tier,
            exc_info=True,
        )


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
        # 同街族子站（2026-11-07 同街族并卡案）：已折进主卡 stops 的族员就是
        # 行程内已有站点——不进排除集就会以备选身份再亮卡（同街族员并
        # 进主卡后仍在备选区冒头实录）
        for s in v.stops or ():
            exclude_names.add(_norm_name(s.name))
            exclude_names.add(_norm_name(s.name_en))
            if s.poi_id:
                exclude_pids.add(str(s.poi_id))
    # 泛化替代组同档成员表（2026-11-07 泛化拍板）：行程里已有的「一行程
    # 一个」档（citywalk）成员按城聚合——attach 层滤城、滤主点本人，
    # 备选闸只补 30km 距离保险（远郊不算同一体验圈）
    from app.services.agent.plan import _generic_substitute_group

    generic_class_names: dict[str, set[str]] = {}
    for v in visits:
        g = _generic_substitute_group((v.category or "").strip())
        if g is None and is_citywalk(v.name, plan_tier=v.tier):
            g = "street"
        if g is not None:
            c = (v.city or "").strip().removesuffix("市")
            if c:
                generic_class_names.setdefault(c, set()).update(
                    {_norm_name(v.name), _norm_name(v.name_en)}
                )
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
                logger.warning(
                    "alternatives: pool query failed for %s (alts empty)",
                    city,
                    exc_info=True,
                )
        row = _main_row(v, store)
        _heal_tier(v, row)
        # 主点 CITYWALK 类：名/梯档之外再认库行功能标签（街巷坊词批打
        # 未全覆盖的兜底）；回库失败按名/梯档自判
        main_cw = is_citywalk(
            v.name,
            (row or {}).get("tags"),
            category=(row or {}).get("category") or v.category,
            plan_tier=v.tier,
        )
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
                main_citywalk=main_cw,
                exclude_same_class=(
                    generic_class_names.get(city, set())
                    - {_norm_name(v.name), _norm_name(v.name_en)}
                )
                or None,
            )
        except Exception:
            alts = []
            logger.warning(
                "alternatives: pick failed for %s (alts empty)",
                v.name,
                exc_info=True,
            )
        v.alternatives = alts or None
        for a in alts:
            used_names.add(_norm_name(a.name))
            used_names.add(_norm_name(a.name_en))
    return copy
