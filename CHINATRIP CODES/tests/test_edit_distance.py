"""条目级编辑距离单测（P6 质量北极星基建）。

夹具风格对齐 tests/test_algo_v0.py：手写最小 ItineraryPlan，不依赖
DB/LLM/HTTP。
"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.edit_distance import (
    DEFAULT_WEIGHTS,
    edit_distance,
)
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)


def _visit(
    item_id: str,
    name: str,
    *,
    day: int,
    poi_id: str | None = None,
    start: tuple[int, int] | None = None,
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        poi_id=poi_id,
        city="上海",
        day=day,
        start_time=time(*start) if start else None,
    )


def _plan(*days: DayPlan) -> ItineraryPlan:
    return ItineraryPlan(itinerary_id="it1", cities=["上海"], days=list(days))


def _day(day: int, *items) -> DayPlan:
    return DayPlan(day=day, base_city="上海", items=list(items))


# --- 基线：完全相同 → 零编辑 -----------------------------------------------


def test_identical_plans_zero_edits():
    a = _plan(
        _day(1, _visit("v1", "甲馆", day=1, poi_id="p1", start=(9, 0))),
        _day(2, _visit("v2", "乙园", day=2, poi_id="p2", start=(10, 0))),
    )
    r = edit_distance(a, a.model_copy(deep=True))
    assert r.counts == {"add": 0, "remove": 0, "move": 0, "retime": 0}
    assert r.weighted_total() == 0.0


# --- 新增 / 删除 ------------------------------------------------------------


def test_add_and_remove():
    orig = _plan(
        _day(1, _visit("v1", "甲馆", day=1, poi_id="p1")),
        _day(2, _visit("v2", "乙园", day=2, poi_id="p2")),
    )
    final = _plan(
        _day(1, _visit("v1", "甲馆", day=1, poi_id="p1")),
        _day(2, _visit("v3", "丙楼", day=2, poi_id="p3")),
    )
    r = edit_distance(orig, final)
    assert r.counts == {"add": 1, "remove": 1, "move": 0, "retime": 0}
    assert r.adds[0].name == "丙楼"
    assert r.removes[0].name == "乙园"
    assert r.weighted_total() == DEFAULT_WEIGHTS["add"] + DEFAULT_WEIGHTS["remove"]


# --- 移动：改天 / 同天改顺序 ------------------------------------------------


def test_move_across_days():
    orig = _plan(
        _day(1, _visit("v1", "甲馆", day=1, poi_id="p1")),
        _day(2, _visit("v2", "乙园", day=2, poi_id="p2")),
    )
    final = _plan(
        _day(
            1,
            _visit("v1", "甲馆", day=1, poi_id="p1"),
            _visit("v2", "乙园", day=1, poi_id="p2"),
        ),
        _day(2),
    )
    r = edit_distance(orig, final)
    assert r.counts["move"] == 1
    assert r.moves[0].from_day == 2 and r.moves[0].to_day == 1
    # move 与 retime 互斥：挪了天不再计改时
    assert r.counts["retime"] == 0


def test_move_within_day_reorder():
    orig = _plan(
        _day(
            1,
            _visit("v1", "甲馆", day=1, poi_id="p1"),
            _visit("v2", "乙园", day=1, poi_id="p2"),
        )
    )
    final = _plan(
        _day(
            1,
            _visit("v2", "乙园", day=1, poi_id="p2"),
            _visit("v1", "甲馆", day=1, poi_id="p1"),
        )
    )
    r = edit_distance(orig, final)
    assert r.counts["move"] == 2  # 两张卡顺序都变了
    assert r.weighted_total() == 2 * DEFAULT_WEIGHTS["move"]


# --- 改时刻 -----------------------------------------------------------------


def test_retime_beyond_tolerance():
    orig = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1", start=(9, 0))))
    final = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1", start=(13, 30))))
    r = edit_distance(orig, final)
    assert r.counts["retime"] == 1
    assert r.retimes[0].from_start_minutes == 9 * 60
    assert r.retimes[0].to_start_minutes == 13 * 60 + 30


def test_retime_within_tolerance_ignored():
    orig = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1", start=(9, 0))))
    final = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1", start=(9, 10))))
    r = edit_distance(orig, final)
    assert r.weighted_total() == 0.0


def test_retime_requires_both_sides_timed():
    # 一侧无时刻：无法判改时，不算 retime（宁缺勿错）
    orig = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1")))
    final = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1", start=(9, 0))))
    r = edit_distance(orig, final)
    assert r.weighted_total() == 0.0


# --- 匹配键：poi_id 优先，名称兜底 ------------------------------------------


def test_match_falls_back_to_name_without_poi_id():
    orig = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id=None)))
    final = _plan(_day(1, _visit("v9", " 甲馆 ", day=1, poi_id=None)))
    r = edit_distance(orig, final)
    assert r.weighted_total() == 0.0


def test_poi_id_change_counts_as_remove_and_add():
    orig = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1")))
    final = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p9")))
    r = edit_distance(orig, final)
    assert r.counts == {"add": 1, "remove": 1, "move": 0, "retime": 0}


def test_duplicate_name_second_card_counts_as_add():
    orig = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1")))
    final = _plan(
        _day(
            1,
            _visit("v1", "甲馆", day=1, poi_id="p1"),
            _visit("v2", "甲馆", day=1, poi_id="p1"),
        )
    )
    r = edit_distance(orig, final)
    assert r.counts["add"] == 1
    assert r.counts["remove"] == 0


# --- 其他：TransferItem 不参与 / summarize / 自定义权重 ---------------------


def test_transfers_not_counted():
    orig = _plan(
        _day(
            1,
            _visit("v1", "甲馆", day=1, poi_id="p1"),
            TransferItem(
                item_id="t1",
                day=1,
                seq=1,
                from_city="上海",
                to_city="杭州",
            ),
        )
    )
    final = _plan(_day(1, _visit("v1", "甲馆", day=1, poi_id="p1")))
    r = edit_distance(orig, final)
    assert r.weighted_total() == 0.0


def test_summarize_shape_and_custom_weights():
    orig = _plan(
        _day(1, _visit("v1", "甲馆", day=1, poi_id="p1")),
        _day(2, _visit("v2", "乙园", day=2, poi_id="p2")),
    )
    final = _plan(_day(1, _visit("v3", "丙楼", day=1, poi_id="p3")))
    weights = {"add": 2.0, "remove": 2.0, "move": 1.0, "retime": 0.5}
    r = edit_distance(orig, final, weights=weights)
    s = r.summarize(weights=weights)
    assert s["counts"] == {"add": 1, "remove": 2, "move": 0, "retime": 0}
    assert s["weighted_total"] == 1 * 2.0 + 2 * 2.0
    assert {op["kind"] for op in s["ops"]} == {"add", "remove"}
