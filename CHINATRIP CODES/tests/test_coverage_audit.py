"""必去覆盖审计（itinerary/request_coverage.py）单测：三分律 + 幂等补披露。"""

from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    UnplacedCandidate,
    VisitItem,
)
from app.services.itinerary.request_coverage import (
    dedupe_unplaced_against_scheduled,
    ensure_must_disclosure,
    missing_must_visits,
)


def _plan(*items, assumptions=None, unplaced=None):
    return ItineraryPlan(
        itinerary_id="it-test",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=list(items))],
        assumptions=list(assumptions or []),
        unplaced=list(unplaced or []),
    )


def _visit(name, name_en=None):
    return VisitItem(
        item_id=f"v-{name}", name=name, name_en=name_en, city="上海", day=1
    )


def test_scheduled_satisfies_trichotomy():
    plan = _plan(_visit("豫园"), _visit("外滩"))
    assert missing_must_visits(plan, ["豫园", "外滩"]) == []


def test_silent_drop_detected_and_disclosed_once():
    plan = _plan(_visit("外滩"))
    must = ["豫园", "外滩", "上海中心大厦"]
    assert missing_must_visits(plan, must) == ["豫园", "上海中心大厦"]
    lines = ensure_must_disclosure(plan, must)
    assert len(lines) == 2
    assert any("豫园" in x for x in plan.assumptions)
    assert any("上海中心大厦" in x for x in plan.assumptions)
    # 幂等：披露已落，二次运行不再补
    assert ensure_must_disclosure(plan, must) == []
    assert missing_must_visits(plan, must) == []


def test_unplaced_and_disclosed_satisfy():
    plan = _plan(
        _visit("外滩"),
        unplaced=[UnplacedCandidate(name="豫园")],
        assumptions=["让位：上海中心大厦因离城日只排轻量街区，移出必去"],
    )
    must = ["豫园", "外滩", "上海中心大厦"]
    assert missing_must_visits(plan, must) == []
    assert ensure_must_disclosure(plan, must) == []


def test_session_level_disclosure_counts():
    plan = _plan(_visit("外滩"))
    # 披露只在会话级（session.assumptions），不在 plan.assumptions——也算已披露
    assert (
        missing_must_visits(
            plan, ["豫园", "外滩"], disclosed=["豫园因时间不够未排入，已让位"]
        )
        == []
    )


def test_containment_and_english_matching():
    plan = _plan(
        _visit("上海中心大厦"),
        _visit("朱家角古镇", name_en="Zhujiajiao Ancient Town"),
    )
    # 用户写短名，卡是全名（包含关系双胞胎语义）
    assert missing_must_visits(plan, ["中心大厦"]) == []
    assert missing_must_visits(plan, ["朱家角"]) == []
    # 英文裸名命中 name_en（大小写/空格不敏感）
    assert missing_must_visits(plan, ["ZHUJIAJIAO"]) == []
    # 双向：必去写全名、卡是正主短名（万国建筑 → 外滩）
    plan2 = _plan(_visit("外滩"))
    assert missing_must_visits(plan2, ["外滩万国建筑博览群"]) == []


def test_transfer_items_ignored_and_no_must_no_noise():
    transfer = TransferItem(
        item_id="t-1", day=1, seq=1, from_city="上海", to_city="杭州", mode="train"
    )
    plan = _plan(transfer, _visit("外滩"))
    assert missing_must_visits(plan, ["外滩"]) == []
    assert missing_must_visits(plan, []) == []
    assert ensure_must_disclosure(plan, []) == []


def test_dedupe_unplaced_removes_exact_duplicates_only():
    plan = _plan(
        _visit("上海中心大厦", name_en="Shanghai Tower"), _visit("外滩源")
    )
    plan.unplaced = [
        UnplacedCandidate(name="上海中心大厦"),
        UnplacedCandidate(name="别的塔", poi_id="p-x"),
        UnplacedCandidate(name="whatever", name_en="Shanghai Tower"),
    ]
    removed = dedupe_unplaced_against_scheduled(plan)
    assert [u.name for u in removed] == ["上海中心大厦", "whatever"]
    assert [u.name for u in plan.unplaced] == ["别的塔"]


def test_dedupe_unplaced_by_poi_id():
    plan = _plan(_visit("观光厅", name_en="Observatory"))
    plan.days[0].items[0].poi_id = "poi-42"
    plan.unplaced = [UnplacedCandidate(name="全然不同的名字", poi_id="poi-42")]
    removed = dedupe_unplaced_against_scheduled(plan)
    assert len(removed) == 1
    assert plan.unplaced == []


def test_dedupe_unplaced_keeps_twin_names():
    # 互含不算同体：外滩源已排，外滩是另一个景点，chip 必须保留
    plan = _plan(_visit("外滩源"))
    plan.unplaced = [UnplacedCandidate(name="外滩"), UnplacedCandidate(name="外滩")]
    removed = dedupe_unplaced_against_scheduled(plan)
    assert removed == []
    assert [u.name for u in plan.unplaced] == ["外滩", "外滩"]


def test_dedupe_unplaced_noop_on_empty():
    plan = _plan(_visit("外滩"))
    assert dedupe_unplaced_against_scheduled(plan) == []
    empty_days = ItineraryPlan(itinerary_id="it-x", cities=[], days=[])
    empty_days.unplaced = [UnplacedCandidate(name="豫园")]
    assert dedupe_unplaced_against_scheduled(empty_days) == []
