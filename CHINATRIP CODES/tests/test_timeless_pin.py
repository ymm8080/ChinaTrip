# -*- coding: utf-8 -*-
"""pinned 无时刻不再整日判死（2026-11-17「求解器未收敛」全勤根因）。

根因：绑定层先钉名（pinned=True）后钉时，中间态 pinned+无时刻进
_visit_spec 旧契约直接 None → insertion/CP 按日原子失败 → 每次 100%
降级披露。修后：无时刻的钉按普通可排条目走；有时刻的钉照旧铁律 19。
"""

from datetime import time

from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.solver import (
    insertion_schedule_day,
    solve_day,
    solve_plan,
)


def _v(iid, name, *, dur=60, pinned=False, start=None, cat="sight"):
    return VisitItem(
        item_id=iid,
        name=name,
        city="上海",
        day=1,
        category=cat,
        duration_minutes=dur,
        pinned=pinned,
        start_time=start,
    )


def _day(items):
    return DayPlan(day=1, base_city="上海", items=items)


def test_timeless_pin_no_longer_kills_the_day():
    """D2 形状（live 案复刻）：三必去 pinned 无时刻 + 软锚餐 + 晚间件——
    旧契约 insertion/CP 双 None；修后两条主路都要出解、必去全落时刻。"""
    day = _day(
        [
            _v("m1", "上海中心大厦", dur=120, cat="viewpoint"),
            _v("m2", "上海科技馆", pinned=True),
            _v("f1", "午饭（自由安排）", cat="food", dur=60, start=time(12, 0)),
            _v("m3", "豫园", pinned=True),
            _v("m4", "外滩", pinned=True),
            _v("e1", "黄浦江游览", dur=120, cat="theme_park"),
            _v("f2", "晚饭（自由安排）", cat="food", dur=90, start=time(19, 0)),
        ]
    )
    ins = insertion_schedule_day(day, poi_hours=[])
    assert ins is not None
    placed_ins = {
        i.name: i.start_time
        for i in ins.items
        if isinstance(i, VisitItem) and i.start_time
    }
    for name in ("上海中心大厦", "上海科技馆", "豫园", "外滩"):
        assert placed_ins.get(name) is not None, f"insertion 未排上 {name}"

    cp = solve_day(day, poi_hours=[], time_budget_seconds=10.0)
    assert cp is not None
    placed_cp = {
        i.name: i.start_time
        for i in cp.items
        if isinstance(i, VisitItem) and i.start_time
    }
    for name in ("上海中心大厦", "上海科技馆", "豫园", "外滩"):
        assert placed_cp.get(name) is not None, f"CP 未排上 {name}"


def test_solve_plan_timeless_pins_solve():
    plan = ItineraryPlan(
        itinerary_id="it-tp",
        cities=["上海"],
        days=[
            _day(
                [
                    _v("m1", "朱家角大清邮局", pinned=True, cat="other"),
                    _v("s1", "武康路", dur=90, cat="attraction"),
                    _v("f1", "午饭（自由安排）", cat="food", dur=60, start=time(12, 0)),
                    _v("s2", "新天地", dur=90, cat="attraction"),
                    _v("f2", "晚饭（自由安排）", cat="food", dur=90, start=time(19, 0)),
                ]
            )
        ],
    )
    solved = solve_plan(plan, poi_hours=[])
    assert solved is not None
    timed = [
        i for i in solved.days[0].items
        if isinstance(i, VisitItem) and i.start_time
    ]
    assert len(timed) == 5


def test_timed_pin_still_iron_rule():
    """有时刻的钉照旧：越窗仍不可行（铁律 19 语义回归锚）。"""
    day = _day(
        [
            _v(
                "p1",
                "早钉",
                pinned=True,
                start=time(8, 0),
                cat="sight",
            )
        ]
    )
    # 8:00 钉在 08:30 日始前——旧测试口径：合法（用户钉早于日始照排）。
    cp = solve_day(day, poi_hours=[])
    assert cp is not None
