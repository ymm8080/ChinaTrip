"""Mutation pipeline tests (§6.0 iron rule 0): apply_diffs / summarize / mutate."""

from datetime import time

import pytest

from app.services.itinerary import (
    DayPlan,
    DiffOp,
    ItineraryPlan,
    PipelineError,
    RuleSeverity,
    VisitItem,
    apply_diffs,
    mutate,
    summarize_changes,
)


def visit(item_id, day, start=None, end=None, *, dur=None, pinned=False):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        day=day,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
        pinned=pinned,
        city="上海",
    )


def base_plan(pinned_a=False):
    return ItineraryPlan(
        itinerary_id="t1",
        cities=["上海"],
        days=[
            DayPlan(
                day=1,
                base_city="上海",
                items=[
                    visit("a", 1, time(9), time(10, 30), dur=90, pinned=pinned_a),
                    visit("b", 1, time(11), time(12), dur=60),
                ],
            ),
            DayPlan(
                day=2,
                base_city="上海",
                items=[visit("c", 2, time(9), time(10), dur=60)],
            ),
        ],
    )


def ids_of(plan, day):
    return [i.item_id for i in plan.days[day - 1].items]


# --- apply_diffs: add ------------------------------------------------------


def test_apply_add_appends_to_day_and_keeps_input_untouched():
    plan = base_plan()
    snapshot = plan.model_copy(deep=True)
    new = apply_diffs(plan, [DiffOp(op="add", item=visit("d", 2, time(13), time(14)))])
    assert ids_of(new, 2) == ["c", "d"]
    assert plan == snapshot  # 入参未被改动
    assert new is not plan


def test_apply_add_without_item_raises():
    with pytest.raises(PipelineError):
        apply_diffs(base_plan(), [DiffOp(op="add")])


def test_apply_add_to_missing_day_raises():
    with pytest.raises(PipelineError):
        apply_diffs(base_plan(), [DiffOp(op="add", item=visit("x", 9, time(9)))])


# --- apply_diffs: remove ---------------------------------------------------


def test_apply_remove_deletes_item():
    new = apply_diffs(base_plan(), [DiffOp(op="remove", item_id="a")])
    assert ids_of(new, 1) == ["b"]


def test_apply_remove_unknown_id_raises():
    with pytest.raises(PipelineError):
        apply_diffs(base_plan(), [DiffOp(op="remove", item_id="zz")])


# --- apply_diffs: move -----------------------------------------------------


def test_apply_move_relocates_and_retimes():
    new = apply_diffs(
        base_plan(),
        [DiffOp(op="move", item_id="a", new_day=2, new_start_time=time(14))],
    )
    assert ids_of(new, 1) == ["b"]
    moved = new.days[1].items[-1]
    assert (moved.item_id, moved.day, moved.start_time) == ("a", 2, time(14))
    assert moved.end_time == time(15, 30)  # start + 90min 重算


def test_apply_move_without_new_day_raises():
    with pytest.raises(PipelineError):
        apply_diffs(base_plan(), [DiffOp(op="move", item_id="a")])


def test_apply_move_to_missing_day_raises():
    with pytest.raises(PipelineError):
        apply_diffs(base_plan(), [DiffOp(op="move", item_id="a", new_day=5)])


# --- apply_diffs: retime ---------------------------------------------------


def test_apply_retime_updates_start_and_recomputes_end():
    new = apply_diffs(
        base_plan(), [DiffOp(op="retime", item_id="b", new_start_time=time(13))]
    )
    retimed = new.days[0].items[1]
    assert (retimed.start_time, retimed.end_time) == (time(13), time(14))


def test_apply_retime_without_new_time_raises():
    with pytest.raises(PipelineError):
        apply_diffs(base_plan(), [DiffOp(op="retime", item_id="b")])


# --- apply_diffs: purity / composition --------------------------------------


def test_apply_diffs_never_mutates_input_across_all_ops():
    plan = base_plan()
    snapshot = plan.model_copy(deep=True)
    apply_diffs(
        plan,
        [
            DiffOp(op="add", item=visit("d", 1, time(15), time(16))),
            DiffOp(op="remove", item_id="b"),
            DiffOp(op="move", item_id="c", new_day=1, new_start_time=time(17)),
            DiffOp(op="retime", item_id="a", new_start_time=time(8)),
        ],
    )
    assert plan == snapshot


# --- summarize_changes ------------------------------------------------------


def test_summarize_one_line_per_diff_with_day_and_time():
    plan = base_plan()
    diffs = [
        DiffOp(op="move", item_id="a", new_day=2, new_start_time=time(14, 30)),
        DiffOp(op="retime", item_id="b", new_start_time=time(13)),
    ]
    s = summarize_changes(diffs, plan=plan)
    assert s.affected_items_count == 2
    assert s.change_summary == [
        "第2天 移动 a 到 14:30",
        "第1天 调整 b 时间到 13:00",
    ]


def test_summarize_add_remove_and_dedup_count():
    diffs = [
        DiffOp(op="add", item=visit("d", 1, time(15), time(16))),
        DiffOp(op="remove", item_id="a"),
        DiffOp(op="retime", item_id="a", new_start_time=time(13)),  # 同一 item 再动
    ]
    s = summarize_changes(diffs, plan=base_plan())
    assert s.affected_items_count == 2  # a 去重
    assert s.change_summary[0] == "第1天 新增 d"
    assert s.change_summary[1] == "第1天 移除 a"


def test_summarize_without_plan_falls_back_to_item_id():
    s = summarize_changes([DiffOp(op="remove", item_id="a")])
    assert s.change_summary == ["移除 a"]
    assert s.affected_items_count == 1


# --- mutate: iron rule 0 one-shot pipeline -----------------------------------


def test_mutate_clean_change_full_pipeline():
    old = base_plan()
    new, report, summary = mutate(
        old,
        [DiffOp(op="retime", item_id="c", new_start_time=time(10))],
        poi_hours=[],
        from_day=2,
        old_plan=old,
    )
    assert new.days[1].items[0].start_time == time(10)
    assert new.days[1].items[0].end_time == time(11)
    assert report.ok
    assert report.violations == []  # scope: 第 1 天原样；节奏/时间均干净
    assert summary.affected_items_count == 1
    assert summary.change_summary == ["第2天 调整 c 时间到 10:00"]
    assert old.days[1].items[0].start_time == time(9)  # 入参未动


def test_mutate_stacks_pinned_violation_into_report():
    old = base_plan(pinned_a=True)
    new, report, summary = mutate(
        old,
        [DiffOp(op="retime", item_id="a", new_start_time=time(13))],
        poi_hours=[],
        from_day=1,
        old_plan=old,
    )
    pinned_hits = [v for v in report.violations if v.rule_id == 19]
    assert len(pinned_hits) == 1
    assert pinned_hits[0].severity == RuleSeverity.error
    assert not report.ok
    assert new.days[0].items[0].start_time == time(13)  # diff 仍被应用
    assert summary.affected_items_count == 1
