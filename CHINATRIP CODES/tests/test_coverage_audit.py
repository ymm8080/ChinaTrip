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
    demote_untimed_musts,
    ensure_must_disclosure,
    missing_must_visits,
    unarranged_must_visits,
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
    # 城市前缀修饰：短名必去被全名卡覆盖
    assert missing_must_visits(plan, ["中心大厦"]) == []
    # 通用尾缀（古镇）：短名必去被全名卡覆盖
    assert missing_must_visits(plan, ["朱家角"]) == []
    # 英文裸名命中 name_en（通用尾缀 ancient town；大小写/空格不敏感）
    assert missing_must_visits(plan, ["ZHUJIAJIAO"]) == []


def test_twin_rule_generic_modifier_vs_distinct_site():
    """互含只在「通用修饰」时算同体（2026-11-17 精化）：
    城市前缀/通用尾缀=同一景点；专名性后缀/单字余量/中段互含=不同景点。"""
    covered = _plan(_visit("上海中心大厦"), _visit("杭州西湖"), _visit("西溪湿地"))
    assert missing_must_visits(covered, ["中心大厦"]) == []
    assert missing_must_visits(covered, ["西湖"]) == []
    assert missing_must_visits(covered, ["西溪"]) == []
    square = _plan(_visit("天安门广场"), _visit("故宫博物院"))
    assert missing_must_visits(square, ["天安门"]) == []
    assert missing_must_visits(square, ["故宫"]) == []

    # 外滩源 / 北外滩 与 外滩 是不同景点——余量非通用/单字，不算覆盖
    distinct = _plan(_visit("外滩源"), _visit("北外滩"))
    assert missing_must_visits(distinct, ["外滩"]) == ["外滩"]
    # 反向：必到写全名、排的是邻近短名，同样不算（万国建筑行已停用，
    # 若用户硬写全名，被顶替必须披露而非静默）
    bund = _plan(_visit("外滩"))
    assert missing_must_visits(bund, ["外滩万国建筑博览群"]) == ["外滩万国建筑博览群"]
    # 中段互含不算：奥林匹克 ≠ 北京奥林匹克公园（前置/后置才认）
    mid = _plan(_visit("北京奥林匹克公园"))
    assert missing_must_visits(mid, ["奥林匹克"]) == ["奥林匹克"]


def test_transfer_items_ignored_and_no_must_no_noise():
    transfer = TransferItem(
        item_id="t-1", day=1, seq=1, from_city="上海", to_city="杭州", mode="train"
    )
    plan = _plan(transfer, _visit("外滩"))
    assert missing_must_visits(plan, ["外滩"]) == []
    assert missing_must_visits(plan, []) == []
    assert ensure_must_disclosure(plan, []) == []


def test_dedupe_unplaced_removes_exact_duplicates_only():
    plan = _plan(_visit("上海中心大厦", name_en="Shanghai Tower"), _visit("外滩源"))
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


def test_unarranged_must_visits_lists_unscheduled_only():
    """未排上名册：已排不列；想去/静默都列——H5 非折叠横幅的数据面
    （2026-11-17 一日游案：折叠假设块用户看不见，告知必须一眼可见）。"""
    plan = _plan(_visit("外滩"), unplaced=[UnplacedCandidate(name="豫园")])
    assert unarranged_must_visits(plan, ["外滩", "豫园", "天坛"]) == ["豫园", "天坛"]
    assert unarranged_must_visits(plan, []) == []
    assert unarranged_must_visits(plan, None) == []


def test_unarranged_musts_twin_names_covered():
    plan = _plan(_visit("上海中心大厦"))
    assert unarranged_must_visits(plan, ["中心大厦"]) == []


def test_enumeration_line_is_not_disclosure():
    """罗列行对谁都不算披露（2026-11-17 上海一日游案）：『外滩、豫园、
    朱家角古镇 位于出发城市 上海，出发日只安排交通，未列入行程』把三个
    必去塞进一行通用规则话术——名字全在，告知为零，审计必须补专行。"""
    plan = _plan(_visit("迪士尼乐园"))
    plan.assumptions = [
        "外滩、豫园、朱家角古镇 位于出发城市 上海，出发日只安排交通，未列入行程"
    ]
    musts = ["外滩", "豫园", "朱家角古镇"]
    assert missing_must_visits(plan, musts) == musts
    lines = ensure_must_disclosure(plan, musts)
    assert len(lines) == 3
    # 幂等：专行已落（每行只提一个必去=个别披露），二次不补
    assert ensure_must_disclosure(plan, musts) == []
    assert missing_must_visits(plan, musts) == []


def test_single_site_prose_disclosure_still_counts():
    """收窄只打罗列行：单点让位/未排入的散文披露照旧算（旧行为不回退）。"""
    plan = _plan(_visit("外滩"))
    plan.assumptions = ["豫园因时间不够未排入，已让位"]
    assert missing_must_visits(plan, ["豫园", "外滩"]) == []


def test_ensure_must_disclosure_english_lines():
    plan = _plan(_visit("外滩"))
    lines = ensure_must_disclosure(plan, ["豫园"], lang="en")
    assert len(lines) == 1
    assert "Must-visit '豫园'" in lines[0]
    assert missing_must_visits(plan, ["豫园"]) == []


def test_audit_gate_sets_unarranged_musts():
    """出站闸把未排上必去名册落到 plan.unarranged_musts（H5 横幅数据面），
    静默丢失件照旧补披露；幂等。"""
    from app.api.plan import _audit_must_coverage
    from app.services.agent.plan import PlanSession

    session = PlanSession(
        session_id="s-audit-unarranged",
        device_id="d-test",
        must_visits=["外滩", "豫园", "天坛"],
        lang="zh",
        plan=_plan(_visit("外滩"), unplaced=[UnplacedCandidate(name="豫园")]),
    )
    _audit_must_coverage(session)
    assert session.plan.unarranged_musts == ["豫园", "天坛"]
    assert any("天坛" in a for a in session.plan.assumptions)
    # 幂等：二次过闸名册一致，披露不重复
    lines_before = len([a for a in session.plan.assumptions if "未排入行程" in a])
    _audit_must_coverage(session)
    assert session.plan.unarranged_musts == ["豫园", "天坛"]
    assert (
        len([a for a in session.plan.assumptions if "未排入行程" in a]) == lines_before
    )


def test_demote_pinned_non_must_card_stays_placed():
    """手钉卡（pinned、非 must；铁律 19）不降级——用户自己的安排出站保留。"""
    visit = _visit("朱家角古镇")
    visit.pinned = True
    plan = _plan(visit)
    notes = demote_untimed_musts(plan, lang="zh")
    assert notes == []
    assert [i.name for i in plan.days[0].items] == ["朱家角古镇"]
    assert plan.unplaced == []
