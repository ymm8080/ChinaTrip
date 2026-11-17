"""包含关系景点规划页互斥（2026-11-17 用户「万国建筑博览群 IS DUPLICATE
OF THE BUND」→「任何有包含关系的景点 EXCLUSIVE IN THE PLANNING PAGE」）：

外滩万国建筑博览群是外滩沿线的衍生行，两张卡同页=重复。凡「正主名 ⊂ 衍生名」
的对，规划页只允许出现一张卡：二拍「子项目有更高优先权」——被包含的具体子行
（上海之巅观光厅类）压过容器伞名，行程级去重与开局选点都保子项目（服务行豁
免：游船/索道等骑在母景点上的行不是子景点，仍保正主）；补点池由
_in_park_of_existing 挡互含行（既有）。
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


def test_dedupe_keeps_contained_child_regardless_of_order():
    """二拍「子项目有更高优先权」：包含对只留被包含的具体子行。"""
    wanguo = _v("外滩万国建筑博览群")
    bund = _v("外滩")
    keepers, dropped = _dedupe_visit_keepers([wanguo, bund])
    assert [k.name for k in keepers] == ["外滩万国建筑博览群"]
    assert dropped == ["外滩"]
    keepers2, dropped2 = _dedupe_visit_keepers([bund, wanguo])
    assert [k.name for k in keepers2] == ["外滩万国建筑博览群"]
    assert dropped2 == ["外滩"]


def test_dedupe_respects_must_and_pin_on_contained_card():
    """铁律19：任一侧必去/钉住时永不让位（仍只留一张卡）——子项目带
    must/pinned 固然留子项目；母项带 must/pinned 时也压过子项目优先。"""
    keepers, _ = _dedupe_visit_keepers(
        [_v("外滩万国建筑博览群", must=True), _v("外滩")]
    )
    assert [k.name for k in keepers] == ["外滩万国建筑博览群"]
    keepers2, _ = _dedupe_visit_keepers(
        [_v("外滩万国建筑博览群", pinned=True), _v("外滩")]
    )
    assert [k.name for k in keepers2] == ["外滩万国建筑博览群"]
    # 母项钉住：子项目优先让位于铁律19
    keepers3, _ = _dedupe_visit_keepers(
        [_v("外滩万国建筑博览群"), _v("外滩", must=True)]
    )
    assert [k.name for k in keepers3] == ["外滩"]
    keepers4, _ = _dedupe_visit_keepers(
        [_v("外滩万国建筑博览群"), _v("外滩", pinned=True)]
    )
    assert [k.name for k in keepers4] == ["外滩"]


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
    assert dropped == ["外滩"]
    assert any("已合并重复站点" in str(a) for a in plan.assumptions)
    names = [i.name for d in plan.days for i in d.items]
    assert names == ["外滩万国建筑博览群"]


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



def test_dedupe_service_row_child_not_promoted():
    """服务行豁免：游船等「骑在母景点上」的行不是子景点——优先权仍归母项。"""
    lake = _v("西湖", lon=120.1491, lat=30.2431)
    cruise = _v("西湖游船", lon=120.1520, lat=30.2460)
    keepers, dropped = _dedupe_visit_keepers([lake, cruise])
    assert [k.name for k in keepers] == ["西湖"]
    assert dropped == ["西湖游船"]
    keepers2, dropped2 = _dedupe_visit_keepers([cruise, lake])
    assert [k.name for k in keepers2] == ["西湖"]
    assert dropped2 == ["西湖游船"]
