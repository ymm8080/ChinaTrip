"""包含关系景点规划页互斥（2026-11-17 用户「万国建筑博览群 IS DUPLICATE
OF THE BUND」→「任何有包含关系的景点 EXCLUSIVE IN THE PLANNING PAGE」）：

外滩万国建筑博览群是外滩沿线的衍生行，两张卡同页=重复。凡「正主名 ⊂ 衍生名」
的对，规划页只允许出现正主一张卡：行程级去重保正主（不再是先到先得）、开局
选点保正主、补点池由 _in_park_of_existing 挡衍生行（既有）。
"""

from datetime import time

from app.services.agent.plan import (
    _contained_twin_pair,
    _dedupe_visit_keepers,
    _fill_leftover_with_diverse_sights,
    _same_visit,
    dedupe_plan_visits,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    UnplacedCandidate,
    VisitItem,
)


def _v(name, *, must=False, pinned=False, lon=121.4903, lat=31.2398):
    return VisitItem(
        item_id=f"it-{name}",
        name=name,
        city="上海",
        category="nature",
        location=GeoPoint(lon=lon, lat=lat),
        day=1,
        must=must,
        pinned=pinned,
    )


def test_contained_pair_detects_bund_derivative():
    assert _contained_twin_pair("外滩", "外滩万国建筑博览群") == (
        "外滩",
        "外滩万国建筑博览群",
    )
    assert _contained_twin_pair("外滩万国建筑博览群", "外滩") == (
        "外滩",
        "外滩万国建筑博览群",
    )
    assert _contained_twin_pair("外滩", "东方明珠") is None
    # 削尾后等价名不算包含对（朱家角古镇/朱家角镇维持既有口径）
    assert _contained_twin_pair("朱家角古镇", "朱家角镇") is None
    # 动宾句式（意图动词前缀）不算衍生行：richer-twin 语义照旧
    assert _contained_twin_pair("看变脸表演", "变脸表演") is None
    # 括号场馆注记不是名字材料：注记变体不算衍生行（dedupe_gate 回归）
    assert _contained_twin_pair("变脸表演（川剧）", "看变脸表演") is None


def test_same_visit_still_merges_containment_pair():
    assert _same_visit(_v("外滩"), _v("外滩万国建筑博览群")) is True


def test_dedupe_keeps_container_regardless_of_order():
    wanguo = _v("外滩万国建筑博览群")
    bund = _v("外滩")
    keepers, dropped = _dedupe_visit_keepers([wanguo, bund])
    assert [k.name for k in keepers] == ["外滩"]
    assert dropped == ["外滩万国建筑博览群"]
    keepers2, dropped2 = _dedupe_visit_keepers([bund, wanguo])
    assert [k.name for k in keepers2] == ["外滩"]
    assert dropped2 == ["外滩万国建筑博览群"]


def test_dedupe_respects_must_and_pin_on_contained_card():
    """铁律19：衍生卡是必去/钉住时永不让位（仍只留一张卡）。"""
    keepers, _ = _dedupe_visit_keepers(
        [_v("外滩万国建筑博览群", must=True), _v("外滩")]
    )
    assert [k.name for k in keepers] == ["外滩万国建筑博览群"]
    keepers2, _ = _dedupe_visit_keepers(
        [_v("外滩万国建筑博览群", pinned=True), _v("外滩")]
    )
    assert [k.name for k in keepers2] == ["外滩万国建筑博览群"]


def test_dedupe_plan_visits_writes_assumption():
    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[
            DayPlan(
                day=1,
                base_city="上海",
                items=[_v("外滩万国建筑博览群"), _v("外滩")],
            )
        ],
        assumptions=[],
    )
    dropped = dedupe_plan_visits(plan)
    assert dropped == ["外滩万国建筑博览群"]
    assert any("已合并重复站点" in str(a) for a in plan.assumptions)
    names = [i.name for d in plan.days for i in d.items]
    assert names == ["外滩"]


def test_fill_never_adds_contained_row_when_container_planned():
    """补点池既有 _in_park_of_existing 闸：正主在行程里，衍生行不补（回归）。"""
    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[
            DayPlan(
                day=1,
                base_city="上海",
                items=[
                    VisitItem(
                        item_id="it-bund",
                        name="外滩",
                        city="上海",
                        category="nature",
                        location=GeoPoint(lon=121.4903, lat=31.2398),
                        day=1,
                        start_time=time(9, 0),
                        end_time=time(11, 0),
                        duration_minutes=120,
                    )
                ],
            )
        ],
        assumptions=[],
    )
    bench = [
        UnplacedCandidate(
            name="外滩万国建筑博览群",
            category="nature",
            duration_minutes=180,
            location=GeoPoint(lon=121.4888, lat=31.2394),
            city="上海",
            poi_id="wanguo",
        )
    ]
    notes = _fill_leftover_with_diverse_sights(plan, bench=bench)
    names = [i.name for d in plan.days for i in d.items]
    assert "外滩万国建筑博览群" not in names
    assert not notes
