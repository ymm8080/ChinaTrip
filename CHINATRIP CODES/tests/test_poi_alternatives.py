"""同级备选规则测试（2026-11-05 拍板「每个点要有一个备选」）。

规则唯一定义点 app/services/poi_alternatives.py：同级（档类一致，
档 4/5 并社媒档）· 同类（受控类别精确→组放宽）· 同时长（band
max(45, 0.5×游时) 封顶 120）· 同城 · 排除行程内已有。装配层
attach_plan_alternatives 在深拷贝上挂、餐位/酒店不挂、fail-soft。

纯内存测试：pool hit dict 模拟 PoiDetailStore.alternatives_pool 行，
不连 DB（LLM_BACKEND=mock 全离线测试口径）。
"""

import pytest

from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.poi_alternatives import (
    attach_plan_alternatives,
    level_class,
    pick_alternatives,
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
) -> dict:
    return {
        "source_poi_id": pid or f"src_{name}",
        "name": name,
        "name_en": name_en,
        "city": "成都",
        "category": category,
        "rating": rating,
        "rating_count": count,
        "tags": [],
        "suggested_duration_min": duration,
        "location": loc,
        "_tier": tier,
    }


def visit(
    name: str = "都江堰",
    tier: int | None = 0,
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


# --- 层级类 -------------------------------------------------------------


def test_level_class_merges_social_tiers():
    # 档 4 短视频 / 5 小红书并作社媒档；其余档号即类；None=未分层按 10
    assert level_class(4) == 4 and level_class(5) == 4
    assert level_class(0) == 0 and level_class(1) == 1 and level_class(2) == 2
    assert level_class(None) == 10


# --- 同级硬闸 -----------------------------------------------------------


def test_same_level_is_hard_gate():
    # UNESCO 主点：池里 5A/TA/未分层行全出局——绝不跨档
    pool = [
        hit("另一个世遗", 0),
        hit("某5A景区", 1),
        hit("某国际榜点", 2),
        hit("某未分层点", 10),
    ]
    alts = pick_alternatives(pool, category="attraction", tier=0, duration_minutes=120)
    assert [a.name for a in alts] == ["另一个世遗"]


def test_5a_main_point_gets_5a_alternative():
    pool = [hit("某5A备选", 1), hit("某世遗", 0)]
    alts = pick_alternatives(pool, category="attraction", tier=1, duration_minutes=120)
    assert [a.name for a in alts] == ["某5A备选"]
    assert alts[0].level_tag == "5a"


# --- 同类闸（精确→组放宽） ---------------------------------------------


def test_same_category_exact_preferred_over_group():
    pool = [
        hit("同组不同类", 0, category="historic"),
        hit("同类精确", 0, category="attraction"),
    ]
    alts = pick_alternatives(pool, category="attraction", tier=0, duration_minutes=120)
    # 两行都同级同类组，精确类别排前
    assert [a.name for a in alts] == ["同类精确", "同组不同类"]


def test_category_group_fallback_when_exact_missing():
    # 博物馆主点：池里只有 gallery（同文博组）→ 放宽补位
    pool = [hit("某美术馆", 0, category="gallery")]
    alts = pick_alternatives(pool, category="museum", tier=0, duration_minutes=120)
    assert [a.name for a in alts] == ["某美术馆"]
    assert alts[0].category == "gallery"


def test_other_group_category_never_crosses():
    # 博物馆主点：池里只有自然/园林类 → 类别不一致出局
    pool = [hit("某公园", 0, category="park")]
    alts = pick_alternatives(pool, category="museum", tier=0, duration_minutes=120)
    assert alts == []


# --- 同时长闸 -----------------------------------------------------------


def test_duration_band_filters_and_prefers_close():
    pool = [
        hit("带内远一点", 0, duration=160),
        hit("带内最近", 0, duration=130),
        hit("带外太长", 0, duration=300),
    ]
    alts = pick_alternatives(pool, category="attraction", tier=0, duration_minutes=120)
    # band(120)=[60,180]：300 出局；130 比 160 更近排前
    assert [a.name for a in alts] == ["带内最近", "带内远一点"]


def test_unknown_duration_only_fills_shortfall():
    pool = [
        hit("无游时候选", 0, duration=None),
        hit("带内候选", 0, duration=110),
    ]
    alts = pick_alternatives(pool, category="attraction", tier=0, duration_minutes=120)
    assert [a.name for a in alts] == ["带内候选", "无游时候选"]
    # 主点本身无游时：band 不过滤，全部按垫底序给出
    alts2 = pick_alternatives(
        pool, category="attraction", tier=0, duration_minutes=None
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
        tier=0,
        duration_minutes=120,
        exclude_names={"重名行"},
        exclude_pids={"pid_dup"},
    )
    assert [a.name for a in alts] == ["干净候选"]


def test_food_rows_never_suggested():
    pool = [hit("某餐厅", 0, category="美食")]
    alts = pick_alternatives(pool, category="attraction", tier=0, duration_minutes=120)
    assert alts == []


# --- 距离加分 -----------------------------------------------------------


def test_closer_candidate_wins_tie():
    near = hit("近处", 0, loc=(103.62, 31.02))
    far = hit("远处", 0, loc=(104.5, 30.0))
    alts = pick_alternatives(
        pool=[far, near],
        category="attraction",
        tier=0,
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
        visit("都江堰", tier=0, item_id="v1"),
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
    plan = plan_of(visit("都江堰", tier=0, item_id="v1"))
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
        visit("都江堰", tier=0, item_id="v1"),
        visit("青城山", tier=0, item_id="v2", duration=180),
    )
    out = attach_plan_alternatives(plan, store)
    for d in out.days:
        for it in d.items:
            if isinstance(it, VisitItem) and it.alternatives:
                assert all(a.name != "青城山" for a in it.alternatives)


def test_attach_fail_soft_when_store_raises():
    class BoomStore:
        def alternatives_pool(self, city: str) -> list[dict]:
            raise RuntimeError("db down")

    plan = plan_of(visit("都江堰", tier=0, item_id="v1"))
    out = attach_plan_alternatives(plan, BoomStore())
    v = next(i for d in out.days for i in d.items if isinstance(i, VisitItem))
    assert v.alternatives is None


def test_attach_none_store_returns_copy():
    plan = plan_of(visit("都江堰", tier=0, item_id="v1"))
    out = attach_plan_alternatives(plan, None)
    assert out is not plan


@pytest.mark.parametrize(
    "tier_a,tier_b,same",
    [(0, 0, True), (1, 1, True), (4, 5, True), (0, 1, False), (2, 3, False)],
)
def test_level_class_pairs(tier_a, tier_b, same):
    assert (level_class(tier_a) == level_class(tier_b)) is same
