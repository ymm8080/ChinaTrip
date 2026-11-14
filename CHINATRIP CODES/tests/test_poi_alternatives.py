"""同级备选规则测试（2026-11-05 拍板「每个点要有一个备选」）。

规则唯一定义点 app/services/poi_alternatives.py：同类（受控类别精确→
组放宽）· 同时长（band max(45,0.5×游时) 封顶 120，带外出局）· 同级
硬闸（2026-11-06 二拍：档带一致才互备，跨档带出局宁缺——4A 不作
5A/世遗备选实录）· 同城 · 排除行程内已有。装配层 attach_plan_alternatives
在深拷贝上挂、餐位/酒店不挂、fail-soft。

档号口径：行程条目 tier = 选点梯子（1=unesco…6=演出 11=其他）；
候选池 hit `_tier` = hit_tier（0=unesco…9=3a 10=未分层）。
纯内存测试：pool hit dict 模拟 PoiDetailStore.alternatives_pool 行，
不连 DB（LLM_BACKEND=mock 全离线测试口径）。
"""

from datetime import time as _t

import pytest

from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    UnplacedCandidate,
    VisitItem,
)
from app.services.poi_alternatives import (
    _norm_name,
    attach_plan_alternatives,
    level_class,
    pick_alternatives,
    plan_tier_to_pool,
)


def hit(
    name: str,
    tier: int,
    category: str | None = "attraction",
    duration: int | None = 120,
    rating: float | None = 4.5,
    count: int | None = 100,
    pid: str | None = None,
    loc: tuple[float, float] | None = (104.0, 30.6),
    name_en: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    return {
        "source_poi_id": pid or f"src_{name}",
        "name": name,
        "name_en": name_en,
        "city": "成都",
        "category": category,
        "rating": rating,
        "rating_count": count,
        "tags": tags or [],
        "suggested_duration_min": duration,
        "location": loc,
        "_tier": tier,
    }


def visit(
    name: str = "都江堰",
    tier: int | None = 1,  # 选点梯子 1=unesco
    category: str | None = "attraction",
    duration: int | None = 120,
    item_id: str = "v1",
    location: GeoPoint | None = GeoPoint(lon=103.6, lat=31.0),
    **kw,
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        city="成都",
        category=category,
        tier=tier,
        duration_minutes=duration,
        location=location,
        day=1,
        **kw,
    )


def plan_of(*items, day: int = 1) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it_test",
        cities=["成都"],
        days=[DayPlan(day=day, base_city="成都", items=list(items))],
    )


# --- 档号换算 -----------------------------------------------------------


def test_plan_tier_to_pool_ladder():
    # 选点梯子（plan._source_tier）→ 池档号（hit_tier）逐档对齐
    assert plan_tier_to_pool(1) == 0  # unesco
    assert plan_tier_to_pool(2) == 1  # 5a
    assert plan_tier_to_pool(3) == 2  # 国际旅行网站
    assert plan_tier_to_pool(4) == 3  # 国际平台
    assert plan_tier_to_pool(5) == 4  # 短视频
    assert plan_tier_to_pool(6) == "show"  # 演出专项
    assert plan_tier_to_pool(7) == 5  # 小红书
    assert plan_tier_to_pool(8) == 6  # 街区
    assert plan_tier_to_pool(9) == 7  # 风景名胜
    assert plan_tier_to_pool(10) == 8  # 4a
    assert plan_tier_to_pool(11) == 10  # 其他/未分层
    assert plan_tier_to_pool(None) == 10


def test_level_class_merges_social_tiers():
    # 池档 4 短视频 / 5 小红书并作社媒档；None=未分层按 10
    assert level_class(4) == 4 and level_class(5) == 4
    assert level_class(0) == 0 and level_class(1) == 1 and level_class(2) == 2
    assert level_class(None) == 10


# --- 同级硬闸：带内互备，跨带出局（2026-11-06 二拍） --------------------


def test_same_level_ranks_first_then_nearest_disclosed():
    # unesco 主点：池里同档 1 行 + 近档 5A/TA → 同档排前，带内近档按
    # |Δ档| 补位（2026-11-13 名录序：intl 0 / unesco 1 / 5a 2）；
    # 未分层跨档带出局
    pool = [
        hit("另一个世遗", 1),
        hit("某国际榜点", 0),
        hit("某5A景区", 2),
        hit("某未分层点", 10),
    ]
    alts = pick_alternatives(pool, category="attraction", tier=2, duration_minutes=120)
    assert [a.name for a in alts] == ["另一个世遗", "某国际榜点", "某5A景区"]
    assert alts[0].level_tag == "unesco"
    assert alts[1].level_tag == "intl"  # 近档补位亮自身档牌，不冒充同级


def test_cross_band_never_suggested_terracotta_case():
    # 2026-11-06 二拍实录：兵马俑（unesco/5A premium）的备选不得落 4A
    # ——陕西自然博物馆（4A，museum 同类同时长全符）也出局，跨档带硬
    # 闸宁缺不滥
    pool = [
        hit("陕西自然博物馆", 8, category="museum", duration=180),
        hit("华清宫", 1, category="attraction", duration=150),
    ]
    alts = pick_alternatives(
        pool,
        category="museum",
        tier=1,
        duration_minutes=180,
        main_name="秦始皇帝陵博物院",
    )
    assert [a.name for a in alts] == ["华清宫"]


def test_unlayered_restaurant_row_never_for_premium():
    # 2026-11-06 二拍实录：竹间葫芦鸡（图商脏行——餐厅被错标 attraction、
    # 无名录档）不作华清宫（5A premium）备选，跨带出局；无类别脏行
    # （海底捞类）双重出局（跨带 + 类别缺失）
    pool = [
        hit("竹间葫芦鸡(凤林南路店)", 10, category="attraction", duration=None),
        hit("海底捞火锅(博乐里店)", 10, category=None, duration=None),
        hit("某5A同行", 1, category="attraction", duration=150),
    ]
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=2,
        duration_minutes=150,
        main_name="华清宫",
    )
    assert [a.name for a in alts] == ["某5A同行"]


def test_missing_category_candidate_out():
    # 候选类别缺失：同类别无法验证，出局（2026-11-06 二拍硬规则；
    # 带内未知类别行不再垫底补位）
    pool = [hit("无类别同行", 0, category=None, duration=120)]
    alts = pick_alternatives(pool, category="attraction", tier=1, duration_minutes=120)
    assert alts == []


def test_5a_main_point_gets_5a_alternative():
    pool = [hit("某5A备选", 2), hit("某世遗", 1)]
    alts = pick_alternatives(pool, category="attraction", tier=3, duration_minutes=120)
    assert alts[0].name == "某5A备选" and alts[0].level_tag == "5a"
    # 同档不足时近档（unesco Δ1）补位
    assert alts[1].name == "某世遗"


def test_ta_recommendation_pair():
    # 国际旅行网站推荐（TA/LP 榜）主点 ↔ TA 榜备选（用户点名场景）
    pool = [hit("某lp榜点", 0, pid="p2"), hit("某4A点", 8)]
    alts = pick_alternatives(pool, category="attraction", tier=1, duration_minutes=120)
    assert alts[0].name == "某lp榜点" and alts[0].level_tag == "intl"


# --- 同类闸（精确→组放宽） ---------------------------------------------


def test_same_category_exact_preferred_over_group():
    # 综合观光组内：attraction 精确一致排前，museum 同组补位
    pool = [
        hit("同组不同类", 0, category="museum"),
        hit("同类精确", 0, category="attraction"),
    ]
    alts = pick_alternatives(pool, category="attraction", tier=1, duration_minutes=120)
    assert [a.name for a in alts] == ["同类精确", "同组不同类"]


def test_sight_heritage_groups_split():
    # 2026-11-06 拍板二改：attraction/viewpoint/museum/gallery 单独一组，
    # 与人文古迹组（historic/temple/…）拆开——temple 不当 museum 的备选
    pool = [hit("某文殊院", 0, category="temple")]
    alts = pick_alternatives(pool, category="museum", tier=1, duration_minutes=120)
    assert alts == []
    # 反向：观光组主点也不换人文古迹组
    pool2 = [hit("某博物馆", 0, category="museum")]
    alts2 = pick_alternatives(pool2, category="temple", tier=1, duration_minutes=120)
    assert alts2 == []


# --- CITYWALK 类隔离（2026-11-06 拍板） ---------------------------------


def test_citywalk_pairs_only_with_citywalk():
    # 宽窄巷子（名称带「巷子」，街区名录梯档 8 → 池档 6 国内名录带）：
    # 锦里古街（古街，同带）同CityWalk类互备；杜甫草堂（museum 4A，同
    # 带但非街区类——档 6 本身即街区类，故用档 8 作对照组）出局
    pool = [
        hit("锦里古街", 6, category="attraction", duration=90),
        hit("杜甫草堂", 8, category="museum", duration=120),
    ]
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=8,
        duration_minutes=150,
        main_name="宽窄巷子",
    )
    assert [a.name for a in alts] == ["锦里古街"]


def test_non_citywalk_main_never_gets_citywalk_row():
    pool = [hit("锦里古街", 2, category="attraction", duration=90)]
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=3,
        duration_minutes=120,
        main_name="武侯祠",
    )
    assert alts == []


def test_street_catalog_row_is_citywalk_class():
    # 名录街区档（hit_tier 6 = 国家级旅游休闲街区）即 CityWalk 类，
    # 名称无街巷坊词（武侯祠·锦里）也算
    pool = [hit("武侯祠·锦里", 6, category="historic", duration=90)]
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=8,
        duration_minutes=150,
        main_name="宽窄巷子",
    )
    assert [a.name for a in alts] == ["武侯祠·锦里"]


def test_citywalk_tag_kernel_counts():
    # 功能标签批内核：tags 带 citywalk 的行（名称无街巷词）也属该类
    pool = [hit("某创意园区", 6, category="attraction", duration=60, tags=["citywalk"])]
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=8,
        duration_minutes=60,
        main_name="宽窄巷子",
    )
    assert [a.name for a in alts] == ["某创意园区"]


def test_category_group_fallback_when_exact_missing():
    # 博物馆主点：池里只有 gallery（同文博组）→ 放宽补位
    pool = [hit("某美术馆", 0, category="gallery")]
    alts = pick_alternatives(pool, category="museum", tier=1, duration_minutes=120)
    assert [a.name for a in alts] == ["某美术馆"]
    assert alts[0].category == "gallery"


def test_other_group_category_never_crosses():
    # 博物馆主点：池里只有自然/园林类 → 类别不一致出局
    pool = [hit("某公园", 0, category="park")]
    alts = pick_alternatives(pool, category="museum", tier=1, duration_minutes=120)
    assert alts == []


# --- 人文古迹组含文博 + 遗址类隔离（2026-11-06 拍板实录） ---------------


def test_dufu_pairing_wuhou_not_jinsha():
    # 用户拍板实录：杜甫草堂（museum t2）的备选应该是武侯祠（attraction
    # t2，库类别不一致但同人文古迹组），金沙遗址博物馆（museum t2 同级
    # 同类同时长）反而不合适——遗址考古类与园林祠庙类隔离；四川博物院
    # （4A t8）跨档带出局（2026-11-06 二拍同级硬闸）
    pool = [
        hit("成都金沙遗址博物馆", 0, category="museum", duration=120),
        hit("武侯祠", 0, category="attraction", duration=90),
        hit("四川博物院", 8, category="museum", duration=120),
    ]
    alts = pick_alternatives(
        pool,
        category="museum",
        tier=1,  # 杜甫草堂选点梯子档 1（curated intl，2026-11-13 升首档）
        duration_minutes=120,
        main_name="杜甫草堂",
    )
    assert [a.name for a in alts] == ["武侯祠"]
    assert alts[0].level_tag == "intl"  # 同档（t0 国际旅行网站）亮国际榜


def test_ruins_main_never_pairs_with_garden_sites():
    # 反向同闸：金沙遗址博物馆主点不亮园林祠庙类备选（宁缺）
    pool = [
        hit("杜甫草堂", 2, category="museum", duration=120),
        hit("武侯祠", 2, category="attraction", duration=90),
    ]
    alts = pick_alternatives(
        pool,
        category="museum",
        tier=3,
        duration_minutes=120,
        main_name="成都金沙遗址博物馆",
    )
    assert alts == []


def test_ruins_main_pairs_with_ruins_peer():
    pool = [
        hit(
            "广汉三星堆博物馆",
            2,
            category="museum",
            duration=120,
        ),
        hit("杜甫草堂", 2, category="museum", duration=120),
    ]
    # 三星堆名称无「遗址」二字，简介兜底判定（真实库行 intro 必提遗址）
    pool[0]["intro"] = "广汉三星堆遗址博物馆，古蜀文明考古遗址"
    alts = pick_alternatives(
        pool,
        category="museum",
        tier=3,
        duration_minutes=120,
        main_name="成都金沙遗址博物馆",
    )
    # 遗址↔遗址放行（三星堆虽属德阳，此处只验名称闸；同城闸在 attach 层）
    assert [a.name for a in alts] == ["广汉三星堆博物馆"]


def test_wuhou_main_pairs_with_dufu():
    # 反向配对：武侯祠主点 ↔ 杜甫草堂（同级同组同 band）
    pool = [
        hit("杜甫草堂", 2, category="museum", duration=120),
        hit("成都金沙遗址博物馆", 2, category="museum", duration=120),
    ]
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=3,
        duration_minutes=90,
        main_name="武侯祠",
    )
    assert [a.name for a in alts] == ["杜甫草堂"]


def test_ruins_subhall_never_suggested_for_umbrella():
    # 遗迹馆/遗址馆是遗址本体的子馆，不当任何点的备选
    pool = [hit("金沙遗址博物馆-遗迹馆", 10, category="museum", duration=60)]
    alts = pick_alternatives(
        pool,
        category="museum",
        tier=3,
        duration_minutes=120,
        main_name="杜甫草堂",
        exclude_names={"成都金沙遗址博物馆"},
    )
    assert alts == []


def test_same_entity_inserted_char_variant_out():
    # 2026-11-06 活库探针实录：兵马俑（秦始皇帝陵博物院）卡亮「秦始皇陵」
    # chip——「帝」字插入变体逃过头尾互含与同核包含，≥3 字核子序列同体
    # 闸兜住（同体行不作备选）
    pool = [hit("秦始皇陵", 0, category="attraction", duration=120)]
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=1,
        duration_minutes=180,
        main_name="秦始皇帝陵博物院",
    )
    assert alts == []


# --- 同时长闸 -----------------------------------------------------------


def test_duration_band_filters_and_prefers_close():
    pool = [
        hit("带内远一点", 0, duration=160),
        hit("带内最近", 0, duration=130),
        hit("带外太长", 0, duration=300),
    ]
    alts = pick_alternatives(pool, category="attraction", tier=1, duration_minutes=120)
    # band(120)=[60,180]：300 出局；130 比 160 更近排前
    assert [a.name for a in alts] == ["带内最近", "带内远一点"]


def test_unknown_duration_only_fills_shortfall():
    pool = [
        hit("无游时候选", 0, duration=None),
        hit("带内候选", 0, duration=110),
    ]
    alts = pick_alternatives(pool, category="attraction", tier=1, duration_minutes=120)
    assert [a.name for a in alts] == ["带内候选", "无游时候选"]
    # 主点本身无游时：band 不过滤，全部同级同类放行
    alts2 = pick_alternatives(
        pool, category="attraction", tier=1, duration_minutes=None
    )
    assert {a.name for a in alts2} == {"无游时候选", "带内候选"}


# --- 排除与去重 ---------------------------------------------------------


def test_excludes_in_plan_names_and_pids():
    pool = [
        hit("行程里已有", 0, pid="pid_dup"),
        hit("重名行", 0, pid="pid_new"),
        hit("干净候选", 0, pid="pid_ok"),
    ]
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=1,
        duration_minutes=120,
        exclude_names={"重名行"},
        exclude_pids={"pid_dup"},
    )
    assert [a.name for a in alts] == ["干净候选"]


def test_food_rows_never_suggested():
    pool = [hit("某餐厅", 0, category="美食")]
    alts = pick_alternatives(pool, category="attraction", tier=1, duration_minutes=120)
    assert alts == []


# --- 演出专项 -----------------------------------------------------------


def test_show_main_point_gets_show_alternatives():
    pool = [
        hit("某演出", 10, category="entertainment", tags=["show"]),
        hit("某景点", 0),
    ]
    alts = pick_alternatives(
        pool, category="entertainment", tier=6, duration_minutes=80
    )
    assert [a.name for a in alts] == ["某演出"]


def test_show_never_alternative_for_sights():
    pool = [hit("某演出", 10, category="entertainment", tags=["show"])]
    alts = pick_alternatives(pool, category="attraction", tier=1, duration_minutes=120)
    assert alts == []


# --- 距离加分 -----------------------------------------------------------


def test_closer_candidate_wins_tie():
    near = hit("近处", 0, loc=(103.62, 31.02))
    far = hit("远处", 0, loc=(104.5, 30.0))
    alts = pick_alternatives(
        pool=[far, near],
        category="attraction",
        tier=1,
        duration_minutes=120,
        near=GeoPoint(lon=103.6, lat=31.0),
    )
    assert alts[0].name == "近处"
    assert alts[0].distance_km is not None and alts[0].distance_km < 10


# --- 装配层 -------------------------------------------------------------


class FakeStore:
    def __init__(self, pool: list[dict]):
        self._pool = pool
        self.calls: list[str] = []

    def alternatives_pool(self, city: str) -> list[dict]:
        self.calls.append(city)
        return list(self._pool)


def test_attach_skips_food_and_hotel_and_transfer():
    store = FakeStore([hit("世遗备选", 0)])
    plan = plan_of(
        visit("都江堰", tier=1, item_id="v1"),
        visit("午餐占位", category="food", duration=60, item_id="v2", soft_pin=True),
        visit(
            "某酒店",
            category="hotel",
            duration=60,
            item_id="v3",
            location=None,
        ),
        TransferItem(item_id="t1", day=1, seq=0, from_city="成都", to_city="重庆"),
    )
    out = attach_plan_alternatives(plan, store)
    by_id = {}
    for d in out.days:
        for it in d.items:
            if isinstance(it, VisitItem):
                by_id[it.item_id] = it
    assert [a.name for a in by_id["v1"].alternatives] == ["世遗备选"]
    assert by_id["v2"].alternatives is None  # 系统餐位不挂
    assert by_id["v3"].alternatives is None  # 酒店卡不挂
    assert store.calls == ["成都"]  # 每城只查一次池


def test_attach_on_copy_original_untouched():
    store = FakeStore([hit("世遗备选", 0)])
    plan = plan_of(visit("都江堰", tier=1, item_id="v1"))
    out = attach_plan_alternatives(plan, store)
    # 本体不带展示数据（持久化会话干净）
    orig = next(i for d in plan.days for i in d.items if isinstance(i, VisitItem))
    assert orig.alternatives is None
    # 返回对象是拷贝不是本体，拷贝上挂了备选
    assert out is not plan
    out_v = next(i for d in out.days for i in d.items if isinstance(i, VisitItem))
    assert out_v.alternatives is not None


def test_attach_excludes_in_plan_sites_from_alternatives():
    # 行程里已有青城山 → 任何卡都不把青城山亮成备选
    store = FakeStore([hit("青城山", 0), hit("世遗备选", 0)])
    plan = plan_of(
        visit("都江堰", tier=1, item_id="v1"),
        visit("青城山", tier=1, item_id="v2", duration=180),
    )
    out = attach_plan_alternatives(plan, store)
    for d in out.days:
        for it in d.items:
            if isinstance(it, VisitItem) and it.alternatives:
                assert all(a.name != "青城山" for a in it.alternatives)


def test_attach_excludes_family_stop_members_from_alternatives():
    # 2026-11-07 钟鼓楼案：同街族并卡后族员折进主卡 stops（钟楼/鼓楼 ⊂
    # 碑林城墙卡）——族员已在行程内，不得再以备选身份亮卡；同档普通
    # 候选不受影响
    from app.services.itinerary.models import PlanStop

    store = FakeStore(
        [
            hit("钟楼", 8, duration=60),
            hit("鼓楼", 8, duration=60),
            hit("某4A同行", 8, duration=90),
        ]
    )
    anchor = visit(
        "西安城墙·碑林历史文化景区",
        tier=10,  # 4a → 池档 8，与钟鼓楼同国内名录带
        duration=180,
        item_id="v1",
    )
    anchor.stops = [
        PlanStop(name="钟楼", poi_id="src_钟楼", duration_minutes=60),
        PlanStop(name="鼓楼", poi_id="src_鼓楼", duration_minutes=60),
    ]
    out = attach_plan_alternatives(plan_of(anchor), store)
    v = next(i for d in out.days for i in d.items if isinstance(i, VisitItem))
    got = [a.name for a in (v.alternatives or [])]
    assert "钟楼" not in got and "鼓楼" not in got
    assert got == ["某4A同行"]


def test_attach_fail_soft_when_store_raises():
    class BoomStore:
        def alternatives_pool(self, city: str) -> list[dict]:
            raise RuntimeError("db down")

    plan = plan_of(visit("都江堰", tier=1, item_id="v1"))
    out = attach_plan_alternatives(plan, BoomStore())
    v = next(i for d in out.days for i in d.items if isinstance(i, VisitItem))
    assert v.alternatives is None


def test_attach_none_store_returns_copy():
    plan = plan_of(visit("都江堰", tier=1, item_id="v1"))
    out = attach_plan_alternatives(plan, None)
    assert out is not plan


def test_attach_heals_tier_from_store_row():
    # 2026-11-06 前换入的行不带 tier（replace_item 漏设）→ 读路径回库以
    # _source_tier 同口径自愈，同档备选不再落 t10 杂馆。_main_row 用
    # candidate_by_name（全量候选形含 tags/source；store.get 是 EN 展示
    # 增补形，无 tags，会把 t2 curated 行错判成 11 实录）。
    class HealingStore(FakeStore):
        def candidate_by_name(self, city: str | None, name: str) -> dict | None:
            if name == "杜甫草堂":
                return {
                    "source": "amap",
                    "source_poi_id": "ct_成都_3",
                    "tags": ["curated", "intl"],
                    "name": "杜甫草堂",
                }
            return None

    store = HealingStore([hit("武侯祠", 2, category="attraction", duration=90)])
    plan = plan_of(
        visit(
            "杜甫草堂",
            tier=None,  # 历史换点行：档号丢失
            category="museum",
            duration=120,
            item_id="v1",
        )
    )
    # poi_id 关联库行
    plan.days[0].items[0].poi_id = "ct_成都_3"
    out = attach_plan_alternatives(plan, store)
    v = next(i for d in out.days for i in d.items if isinstance(i, VisitItem))
    assert v.tier == 1  # curated/intl 标签 → 选点梯子首档（_source_tier 口径）
    assert [a.name for a in v.alternatives] == ["武侯祠"]
    # 本体 tier 仍不动（只治展示拷贝）
    assert plan.days[0].items[0].tier is None


@pytest.mark.parametrize(
    "tier_a,tier_b,same",
    [(0, 0, True), (1, 1, True), (4, 5, True), (0, 1, False), (2, 3, False)],
)
def test_level_class_pairs(tier_a, tier_b, same):
    assert (level_class(tier_a) == level_class(tier_b)) is same


# --- 同体验替代组隔离（2026-11-07 熊猫谷案）--------------------------------


def test_substitute_member_not_offered_when_other_member_in_plan():
    """行程已有熊猫基地时，熊猫谷不再作其它条目（文殊院）的备选亮卡
    ——点了必撞 duplicate_in_plan，宁可不亮。"""
    pool = [hit("熊猫谷", 2, duration=120, loc=(103.59896, 30.96554))]
    exclude = {_norm_name("文殊院"), _norm_name("成都大熊猫繁育研究基地")}
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=3,
        duration_minutes=120,
        exclude_names=exclude,
        main_name="文殊院",
    )
    assert alts == []


def test_substitute_member_offered_for_member_main():
    """主点本人是组员（基地卡）：谷 chip 正常亮——这是「熊猫谷替换熊猫
    基地」的正当替换路径（2026-11-07 拍板），隔离闸不得误伤。"""
    pool = [hit("熊猫谷", 2, duration=120, loc=(103.59896, 30.96554))]
    exclude = {_norm_name("成都大熊猫繁育研究基地"), _norm_name("文殊院")}
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=3,
        duration_minutes=120,
        exclude_names=exclude,
        main_name="成都大熊猫繁育研究基地",
    )
    assert [a.name for a in alts] == ["熊猫谷"]


def test_substitute_member_offered_when_alone():
    """行程无组员时谷照常亮卡（离堆公园的备选）：隔离闸只在「已有另一
    组员」时收口。"""
    pool = [hit("熊猫谷", 2, duration=120, loc=(103.59896, 30.96554))]
    exclude = {_norm_name("离堆公园"), _norm_name("文殊院")}
    alts = pick_alternatives(
        pool,
        category="attraction",
        tier=3,
        duration_minutes=120,
        exclude_names=exclude,
        main_name="离堆公园",
    )
    assert [a.name for a in alts] == ["熊猫谷"]


def test_panda_members_same_category_despite_category_groups():
    """2026-11-07 用户拍板「熊猫基地/谷/苑一个品类」：组员 zoo/nature 跨
    CATEGORY_GROUPS 组（fun vs nature），组内互认精确同类——真实库类别
    （谷=nature、基地=zoo）不再被品类闸杀（首改前谷卡永不亮基地 chip
    实录：cat_key 出局于 467 行同类闸）。"""
    pool = [
        hit(
            "成都大熊猫繁育研究基地",
            2,
            category="zoo",
            duration=180,
            rating=4.6,
            loc=(104.1441, 30.7330),
        )
    ]
    alts = pick_alternatives(
        pool,
        category="nature",
        tier=3,  # 国际旅行网站 → 池档 2，与基地同 premium 带
        duration_minutes=150,
        exclude_names={_norm_name("熊猫谷"), _norm_name("文殊院")},
        main_name="熊猫谷",
    )
    assert [a.name for a in alts] == ["成都大熊猫繁育研究基地"]


def test_panda_member_category_unity_is_bidirectional():
    """反向同闸：基地(zoo)卡亮谷(nature) chip——替换路径双向通。"""
    pool = [
        hit(
            "熊猫谷",
            2,
            category="nature",
            duration=150,
            rating=4.5,
            loc=(103.59896, 30.96554),
        )
    ]
    alts = pick_alternatives(
        pool,
        category="zoo",
        tier=3,
        duration_minutes=180,
        exclude_names={
            _norm_name("成都大熊猫繁育研究基地"),
            _norm_name("文殊院"),
        },
        main_name="成都大熊猫繁育研究基地",
    )
    assert [a.name for a in alts] == ["熊猫谷"]


# --- 泛化品类替代组（2026-11-07 类型+距离拍板）-----------------------------


def test_generic_street_member_blocked_when_other_street_in_plan():
    """行程已有宽窄巷子 → 春熙路（同城 30km 圈内 street 组员）不作其它
    街区条目的备选亮卡——一个行程一条街区。"""
    pool = [
        hit("春熙路", 6, category="citywalk", duration=120, loc=(104.0782, 30.6574))
    ]
    alts = pick_alternatives(
        pool,
        category="citywalk",
        tier=8,
        duration_minutes=120,
        main_name="东郊记忆",
        exclude_names={_norm_name("东郊记忆"), _norm_name("宽窄巷子")},
        exclude_same_class={"宽窄巷子"},
        near=GeoPoint(lon=104.1090, lat=30.6590),
    )
    assert alts == []


def test_generic_street_member_ok_for_member_main():
    """主点本人是街区组员（宽窄巷子卡）：attach 层已把主点本人从
    exclude_same_class 剔除（此处传 None 同形），春熙路 chip 正常亮——
    正当替换路径。"""
    pool = [
        hit("春熙路", 6, category="citywalk", duration=120, loc=(104.0782, 30.6574))
    ]
    alts = pick_alternatives(
        pool,
        category="citywalk",
        tier=8,
        duration_minutes=120,
        main_name="宽窄巷子",
        exclude_names={_norm_name("宽窄巷子")},
        exclude_same_class=None,
        near=GeoPoint(lon=104.0536, lat=30.6637),
    )
    assert [a.name for a in alts] == ["春熙路"]


# --- 「想排未排」chip（2026-11-11 拍板「可替代品不一定同品类，想排没排
# 进去的景点放右边」） ---------------------------------------------------------


def _unplaced(
    name: str = "被挤点",
    city: str = "成都",
    day_hint: int | None = 1,
    category: str | None = "museum",
    tier: int | None = 3,
    duration: int | None = 120,
) -> UnplacedCandidate:
    return UnplacedCandidate(
        name=name,
        city=city,
        day_hint=day_hint,
        category=category,
        tier=tier,
        duration_minutes=duration,
        location=GeoPoint(lon=104.0, lat=30.6),
        reason="yield_must",
    )


def _two_day_plan() -> ItineraryPlan:
    v1 = visit("都江堰", tier=1, item_id="v1")
    v1.start_time = _t(9, 0)
    v2 = visit("武侯祠", tier=3, item_id="v2", category="historic")
    v2.day = 2
    v2.start_time = _t(10, 0)
    return ItineraryPlan(
        itinerary_id="it_want",
        cities=["成都"],
        days=[
            DayPlan(day=1, base_city="成都", items=[v1]),
            DayPlan(day=2, base_city="成都", items=[v2]),
        ],
    )


def test_unplaced_chip_lands_on_hint_day_with_want_badge():
    plan = _two_day_plan()
    plan.unplaced.append(_unplaced(name="某被挤博物馆", day_hint=2))
    out = attach_plan_alternatives(plan, FakeStore([]))
    d1 = out.days[0].items[0]
    d2 = out.days[1].items[0]
    assert d1.alternatives is None, "非 day_hint 天不挂"
    assert [a.name for a in d2.alternatives] == ["某被挤博物馆"]
    assert d2.alternatives[0].level_tag == "want", "想排 chip 亮「想去」徽标"


def test_unplaced_chip_cross_category_allowed():
    """跨品类放行（拍板核心）：museum 被挤点也挂 attraction 主卡右侧。"""
    plan = _two_day_plan()
    plan.unplaced.append(_unplaced(name="某被挤博物馆", day_hint=1, category="museum"))
    out = attach_plan_alternatives(plan, FakeStore([]))
    v1 = out.days[0].items[0]
    assert [a.name for a in v1.alternatives] == ["某被挤博物馆"]


def test_unplaced_chip_skipped_when_already_in_plan():
    """行程内已有同名点（含无时刻灰卡）不再亮「想去」chip，防双亮。"""
    plan = _two_day_plan()
    ghost = visit("某被挤博物馆", tier=3, item_id="v9", category="museum")
    ghost.day = 2  # 无时刻灰卡
    plan.days[1].items.append(ghost)
    plan.unplaced.append(_unplaced(name="某被挤博物馆", day_hint=2))
    out = attach_plan_alternatives(plan, FakeStore([]))
    for d in out.days:
        for it in d.items:
            if isinstance(it, VisitItem) and it.alternatives:
                assert all(a.name != "某被挤博物馆" for a in it.alternatives)


def test_unplaced_chip_food_and_blank_skipped():
    plan = _two_day_plan()
    plan.unplaced.append(_unplaced(name="某餐厅", category="美食"))
    plan.unplaced.append(_unplaced(name=""))
    out = attach_plan_alternatives(plan, FakeStore([]))
    for d in out.days:
        for it in d.items:
            if isinstance(it, VisitItem):
                assert not it.alternatives


def test_unplaced_chip_want_first_and_capped():
    """想排 chip 排最前；同卡 chip 总量仍 ≤ALT_LIMIT（同级备选被截尾）。"""
    from app.services.poi_alternatives import ALT_LIMIT

    pool = [hit(f"同档备选{i}", 0, duration=120) for i in range(ALT_LIMIT)]
    plan = _two_day_plan()
    v1 = plan.days[0].items[0]
    v1.category = "attraction"
    v1.tier = 1
    plan.unplaced.append(_unplaced(name="某被挤点", day_hint=1))
    out = attach_plan_alternatives(plan, FakeStore(pool))
    got = out.days[0].items[0].alternatives
    assert len(got) == ALT_LIMIT
    assert got[0].name == "某被挤点" and got[0].level_tag == "want"
    assert all(a.name != "某被挤点" for a in got[1:])
