"""Iron-rule validator tests (design §6.4): each rule = trigger + clean control."""

from datetime import time

from app.services.itinerary import (
    CrowdProfile,
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    RuleSeverity,
    TransferItem,
    VisitItem,
    validate_change_scope,
    validate_pinned,
    validate_plan,
)

HOURS = [PoiHours(poi_id="p1", opens=time(9, 0), closes=time(17, 0))]


def visit(
    item_id,
    day,
    start=None,
    end=None,
    *,
    city="上海",
    loc=None,
    dur=None,
    pinned=False,
    poi_id=None,
):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        day=day,
        start_time=start,
        end_time=end,
        city=city,
        location=loc,
        duration_minutes=dur,
        pinned=pinned,
        poi_id=poi_id,
    )


def transfer(item_id, day, seq, start=None, end=None, frm="上海", to="苏州"):
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=seq,
        start_time=start,
        end_time=end,
        from_city=frm,
        to_city=to,
    )


def plan(days, cities=("上海", "苏州")):
    return ItineraryPlan(itinerary_id="t1", cities=list(cities), days=days)


def pt(lat):
    return GeoPoint(lon=121.5, lat=lat)


def rule_hits(report, rule_id):
    return [v for v in report.violations if v.rule_id == rule_id]


# --- iron rule 1: time overlap --------------------------------------------


def test_rule1_overlap_is_error():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            visit("a", 1, time(10), time(11, 30)),
            visit("b", 1, time(11), time(12)),
        ],
    )
    rep = validate_plan(plan([d]), poi_hours=[])
    hits = rule_hits(rep, 1)
    assert len(hits) == 1
    assert hits[0].severity == RuleSeverity.error
    assert set(hits[0].item_ids) == {"a", "b"}
    assert not rep.ok


def test_rule1_clean_back_to_back():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[visit("a", 1, time(9), time(10)), visit("b", 1, time(10), time(12))],
    )
    rep = validate_plan(plan([d]), poi_hours=[])
    assert rule_hits(rep, 1) == []
    assert rep.ok


# --- iron rule 2: opening hours -------------------------------------------


def test_rule2_outside_hours_is_error():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[visit("a", 1, time(8), time(8, 30), poi_id="p1")],
    )
    rep = validate_plan(plan([d]), poi_hours=HOURS)
    hits = rule_hits(rep, 2)
    assert len(hits) == 1
    assert hits[0].severity == RuleSeverity.error
    assert hits[0].item_ids == ["a"]
    assert not rep.ok


def test_rule2_within_hours_and_unknown_poi_skipped():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            visit("a", 1, time(10), time(11), poi_id="p1"),
            visit("b", 1, time(20), time(21), poi_id="p_unknown"),  # 无小时数据→跳过
        ],
    )
    rep = validate_plan(plan([d]), poi_hours=HOURS)
    assert rule_hits(rep, 2) == []
    assert rep.ok


# --- iron rule 4: visit <-> transfer buffer --------------------------------


def test_rule4_visit_too_close_to_transfer_is_error():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            transfer("t", 1, 1, time(12), time(14)),
            visit("before", 1, time(10, 30), time(11)),  # 距发车仅 60 分钟
            visit("after", 1, time(15), time(16)),  # 抵达后仅 60 分钟
        ],
    )
    rep = validate_plan(plan([d]), poi_hours=[])
    hits = rule_hits(rep, 4)
    assert len(hits) == 2
    assert all(h.severity == RuleSeverity.error for h in hits)
    assert not rep.ok


def test_rule4_clean_buffer_respected():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            transfer("t", 1, 1, time(12), time(14)),
            visit("a", 1, time(10), time(10, 30)),  # 发车前 90 分钟整 = 达标
            visit("b", 1, time(16), time(17)),  # 抵达后 120 分钟
        ],
    )
    rep = validate_plan(plan([d]), poi_hours=[])
    assert rule_hits(rep, 4) == []
    assert rep.ok


# --- iron rule 5: same-day multi-transfer seq + mutual buffer --------------


def test_rule5_transfer_gap_below_buffer_is_error():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            transfer("t1", 1, 1, time(9), time(11), frm="上海", to="苏州"),
            transfer("t2", 1, 2, time(11, 30), time(13), frm="苏州", to="杭州"),
        ],
    )
    rep = validate_plan(plan([d], cities=("上海", "苏州", "杭州")), poi_hours=[])
    hits = rule_hits(rep, 5)
    assert len(hits) == 1
    assert hits[0].severity == RuleSeverity.error
    assert not rep.ok


def test_rule5_clean_ordered_and_buffered():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            transfer("t1", 1, 1, time(9), time(11), frm="上海", to="苏州"),
            transfer("t2", 1, 2, time(13), time(15), frm="苏州", to="杭州"),
        ],
    )
    rep = validate_plan(plan([d], cities=("上海", "苏州", "杭州")), poi_hours=[])
    assert rule_hits(rep, 5) == []
    assert rep.ok


def test_rule5_duplicate_seq_is_error():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            transfer("t1", 1, 1, time(9), time(11)),
            transfer("t2", 1, 1, time(13), time(15), frm="苏州", to="杭州"),
        ],
    )
    rep = validate_plan(plan([d], cities=("上海", "苏州", "杭州")), poi_hours=[])
    hits = rule_hits(rep, 5)
    assert len(hits) == 1
    assert not rep.ok


# --- iron rule 6: pace (walk distance) --------------------------------------


def test_rule6_walk_over_limit_warns_not_fails():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            visit("a", 1, time(9), time(10), loc=pt(31.20)),
            visit("b", 1, time(11), time(12), loc=pt(31.40)),  # ~22 km
        ],
    )
    rep = validate_plan(plan([d]), poi_hours=[])
    hits = rule_hits(rep, 6)
    assert len(hits) == 1
    assert hits[0].severity == RuleSeverity.warning
    assert "直线距离近似" in hits[0].message
    assert rep.ok  # warning 不算硬失败


def test_rule6_walk_crowd_slow_tighter_limit():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            visit("a", 1, time(9), time(10), loc=pt(31.24)),
            visit("b", 1, time(11), time(12), loc=pt(31.33)),  # ~10 km
        ],
    )
    rep_normal = validate_plan(plan([d]), poi_hours=[])
    rep_slow = validate_plan(plan([d]), poi_hours=[], crowd_profile=CrowdProfile.slow)
    assert rule_hits(rep_normal, 6) == []  # 10km < 15km
    assert len(rule_hits(rep_slow, 6)) == 1  # 10km > 15km*0.6=9km


def test_rule6_walk_clean_short_distance_and_location_gap_skipped():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            visit("a", 1, time(9), time(10), loc=pt(31.23)),
            visit("mid", 1, time(10, 30), time(11)),  # 无 location → 相邻段跳过
            visit("c", 1, time(11, 30), time(12), loc=pt(31.40)),
        ],
    )
    rep = validate_plan(plan([d]), poi_hours=[])
    assert rule_hits(rep, 6) == []
    assert rep.ok


# --- iron rule 6: pace (effective tour ratio) -------------------------------


def test_rule6_low_tour_ratio_warns():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            visit("a", 1, time(9), time(10, 30), dur=90),
            visit("b", 1, time(16), time(18)),  # span 540 分钟，Σdur=90 → 17%
        ],
    )
    rep = validate_plan(plan([d]), poi_hours=[])
    hits = rule_hits(rep, 6)
    assert len(hits) == 1
    assert hits[0].severity == RuleSeverity.warning
    assert rep.ok


def test_rule6_healthy_ratio_clean():
    d = DayPlan(
        day=1,
        base_city="上海",
        items=[
            visit("a", 1, time(9), time(10, 30), dur=90),
            visit("b", 1, time(10, 40), time(12, 10), dur=90),  # 180/190 ≈ 95%
        ],
    )
    rep = validate_plan(plan([d]), poi_hours=[])
    assert rule_hits(rep, 6) == []
    assert rep.ok


# --- iron rule 3 (simplified): geography sanity -----------------------------


def test_rule3_unknown_visit_city_warns():
    d = DayPlan(
        day=1, base_city="上海", items=[visit("a", 1, time(9), time(10), city="拉萨")]
    )
    rep = validate_plan(plan([d], cities=("上海",)), poi_hours=[])
    hits = rule_hits(rep, 3)
    assert len(hits) == 1
    assert hits[0].severity == RuleSeverity.warning
    assert rep.ok


def test_rule3_base_city_jump_without_transfer_warns():
    days = [
        DayPlan(day=1, base_city="上海", items=[visit("a", 1, time(9), time(10))]),
        DayPlan(day=2, base_city="苏州", items=[visit("b", 2, time(9), time(10))]),
    ]
    rep = validate_plan(plan(days), poi_hours=[])
    hits = rule_hits(rep, 3)
    assert len(hits) == 1
    assert "跳变" in hits[0].message


def test_rule3_base_city_jump_with_transfer_clean():
    days = [
        DayPlan(day=1, base_city="上海", items=[visit("a", 1, time(8), time(9))]),
        DayPlan(
            day=2,
            base_city="苏州",
            items=[
                transfer("t", 2, 1, time(10), time(12)),
                visit("b", 2, time(14), time(15)),
            ],
        ),
    ]
    rep = validate_plan(plan(days), poi_hours=[])
    hits = rule_hits(rep, 3)
    assert hits == []
    assert rep.ok


def test_rule3_city_suffix_shi_normalized_clean():
    # LLM 写 "上海市"，行程城市是 "上海" —— 同城不得报警
    d = DayPlan(
        day=1, base_city="上海", items=[visit("a", 1, time(9), time(10), city="上海市")]
    )
    rep = validate_plan(plan([d], cities=("上海",)), poi_hours=[])
    assert rule_hits(rep, 3) == []


def test_rule3_base_city_jump_transfer_on_departure_day_clean():
    # 跨城交通在切换前一天（出发日）：day1 乘车离开上海，day2 base=苏州，合法
    days = [
        DayPlan(
            day=1,
            base_city="上海",
            items=[
                transfer("t", 1, 1, time(10), time(12)),
                visit("a", 1, time(14), time(15), city="苏州"),
            ],
        ),
        DayPlan(day=2, base_city="苏州", items=[visit("b", 2, time(9), time(10))]),
    ]
    rep = validate_plan(plan(days), poi_hours=[])
    assert rule_hits(rep, 3) == []
    assert rep.ok


def test_rule3_base_city_suffix_only_not_a_jump():
    # "上海市" → "上海" 只是后缀差异，不是城市跳变
    days = [
        DayPlan(day=1, base_city="上海市", items=[visit("a", 1, time(9), time(10))]),
        DayPlan(day=2, base_city="上海", items=[visit("b", 2, time(9), time(10))]),
    ]
    rep = validate_plan(plan(days), poi_hours=[])
    assert rule_hits(rep, 3) == []


# --- iron rule 10: change scope ---------------------------------------------


def old_and_new(day1_items, day2_items):
    old = plan(
        [
            DayPlan(day=1, base_city="上海", items=day1_items[0]),
            DayPlan(day=2, base_city="苏州", items=day2_items[0]),
        ]
    )
    new = plan(
        [
            DayPlan(day=1, base_city="上海", items=day1_items[1]),
            DayPlan(day=2, base_city="苏州", items=day2_items[1]),
        ]
    )
    return old, new


def test_rule10_touching_day_before_from_day_is_error():
    old, new = old_and_new(
        (
            [visit("a", 1, time(9), time(10))],
            [visit("a", 1, time(11), time(12))],  # 第 1 天被改
        ),
        (
            [visit("b", 2, time(9), time(10))],
            [visit("b", 2, time(9), time(10))],
        ),
    )
    rep = validate_change_scope(old, new, from_day=2)
    assert not rep.ok
    assert rep.violations[0].rule_id == 10
    assert rep.violations[0].day == 1


def test_rule10_clean_when_only_from_day_onward_changed():
    old, new = old_and_new(
        (
            [visit("a", 1, time(9), time(10))],
            [visit("a", 1, time(9), time(10))],
        ),
        (
            [visit("b", 2, time(9), time(10))],
            [visit("b", 2, time(15), time(16))],  # 第 2 天被改
        ),
    )
    rep = validate_change_scope(old, new, from_day=2)
    assert rep.ok
    assert rep.violations == []


# --- iron rule 19: pinned items ----------------------------------------------


def test_rule19_pinned_moved_is_error():
    old = plan(
        [
            DayPlan(
                day=1,
                base_city="上海",
                items=[visit("a", 1, time(9), time(10), pinned=True)],
            )
        ]
    )
    new = plan(
        [
            DayPlan(
                day=1,
                base_city="上海",
                items=[visit("a", 1, time(11), time(12), pinned=True)],
            )
        ]
    )
    rep = validate_pinned(old, new)
    assert not rep.ok
    assert rep.violations[0].rule_id == 19


def test_rule19_pinned_deleted_is_error():
    old = plan(
        [
            DayPlan(
                day=1,
                base_city="上海",
                items=[visit("a", 1, time(9), time(10), pinned=True)],
            )
        ]
    )
    new = plan([DayPlan(day=1, base_city="上海", items=[])])
    rep = validate_pinned(old, new)
    assert not rep.ok
    assert rep.violations[0].rule_id == 19
    assert "删除" in rep.violations[0].message


def test_rule19_pinned_intact_clean():
    items = [
        visit("a", 1, time(9), time(10), pinned=True),
        visit("b", 1, time(11), time(12)),
    ]
    old = plan([DayPlan(day=1, base_city="上海", items=items)])
    new = plan(
        [
            DayPlan(
                day=1,
                base_city="上海",
                items=[
                    visit("a", 1, time(9), time(10), pinned=True),
                    visit("b", 1, time(13), time(14)),  # 未钉死项随便动
                ],
            )
        ]
    )
    rep = validate_pinned(old, new)
    assert rep.ok
    assert rep.violations == []
