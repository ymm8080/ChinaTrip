# -*- coding: utf-8 -*-
"""景点链顺序 vs 方向（2026-11-14 用户「ABCD 也可以 DCBA；方向不同，
但景点顺序应地理相邻一致」）。

链由 solver 的 AddCircuit travel objective 最小化相邻走行决定；方向
由固定锚点（演出时间第一、餐卡时间第二）决定——锚点腿也是总走行的一
部分，所以同一地理链会朝锚点端翻转。餐卡绑定层只顺延时刻，绝不重排链。
"""

from datetime import time

from app.services.agent.plan import _bind_real_food_to_cards
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.itinerary.solver import solve_day


def _visit(
    iid: str,
    name: str,
    lon: float,
    lat: float,
    *,
    start: time | None = None,
    dur: int = 60,
    cat: str = "attraction",
    **kw,
) -> VisitItem:
    end = None
    if start is not None:
        m = start.hour * 60 + start.minute + dur
        end = time(m // 60, m % 60)
    return VisitItem(
        item_id=iid,
        name=name,
        poi_id=iid,
        category=cat,
        city="测试",
        location=GeoPoint(lon=lon, lat=lat),
        day=1,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
        **kw,
    )


def _square(anchor: VisitItem) -> tuple[DayPlan, dict[tuple[str, str], int]]:
    """正方形 A(0,0) B(0,1) C(1,1) D(1,0)；anchor 在 A 点。"""
    day = DayPlan(
        day=1,
        base_city="测试",
        items=[
            _visit("a", "A", 0, 0),
            _visit("b", "B", 0, 1),
            _visit("c", "C", 1, 1),
            _visit("d", "D", 1, 0),
            anchor,
        ],
    )
    pts = {"a": (0, 0), "b": (0, 1), "c": (1, 1), "d": (1, 0), anchor.item_id: (0, 0)}
    matrix = {
        (i, j): round(
            (((pts[j][0] - pts[i][0]) ** 2 + (pts[j][1] - pts[i][1]) ** 2) ** 0.5) * 20
        )
        for i in pts
        for j in pts
        if i != j
    }
    return day, matrix


def _sight_names(out: DayPlan) -> list[str]:
    return [i.name for i in out.items if (i.category or "") == "attraction"]


def _assert_adjacent_chain(names: list[str]) -> None:
    coords = {"A": (0, 0), "B": (0, 1), "C": (1, 1), "D": (1, 0)}
    for a, b in zip(names, names[1:]):
        assert abs(coords[a][0] - coords[b][0]) + abs(coords[a][1] - coords[b][1]) == 1


def test_solver_flips_adjacent_chain_toward_show_at_opposite_end():
    """演出 18:00 在 A 点 → 链保持相邻，方向翻到 A 端收尾（B-C-D-A）。"""
    show = _visit(
        "s",
        "演出",
        0,
        0,
        start=time(18, 0),
        dur=60,
        cat="entertainment",
        pinned=True,
        soft_pin=False,
    )
    day, matrix = _square(show)
    out = solve_day(day, poi_hours=[], travel_minutes=matrix, time_budget_seconds=5)
    assert out is not None
    names = _sight_names(out)
    assert len(names) == 4
    _assert_adjacent_chain(names)
    assert names[-1] == "A"  # 演出前最后一站=A（同址）


def test_solver_flips_adjacent_chain_toward_dinner_card():
    """无演出时，18:00 晚餐卡在 A 点 → 同一相邻链翻到 A 端收尾。"""
    dinner = _visit(
        "r",
        "晚餐",
        0,
        0,
        start=time(18, 0),
        dur=60,
        cat="food",
        pinned=True,
        soft_pin=False,
    )
    day, matrix = _square(dinner)
    out = solve_day(day, poi_hours=[], travel_minutes=matrix, time_budget_seconds=5)
    assert out is not None
    names = _sight_names(out)
    assert len(names) == 4
    _assert_adjacent_chain(names)
    assert names[-1] == "A"


def test_card_binding_never_reorders_the_sight_chain():
    """餐卡绑定只挪时刻，不改景点链顺序（ABCD 仍是 ABCD）。"""
    items = [
        _visit("a", "A", 0, 0, start=time(9, 0), dur=60),
        _visit("b", "B", 0, 1, start=time(10, 20), dur=60),
        _visit("c", "C", 1, 1, start=time(11, 40), dur=60),
        _visit("d", "D", 1, 0, start=time(13, 0), dur=60),
        _visit(
            "food-d1-lunch-1",
            "同址餐厅",
            0,
            1,
            start=time(16, 15),
            dur=30,
            cat="food",
            soft_pin=True,
        ),
    ]
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["测试"],
        days=[DayPlan(day=1, base_city="测试", items=items)],
    )
    _bind_real_food_to_cards(plan)
    names = _sight_names(plan.days[0])
    assert names == ["A", "B", "C", "D"]
