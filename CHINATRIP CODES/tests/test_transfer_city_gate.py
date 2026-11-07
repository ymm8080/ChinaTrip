# -*- coding: utf-8 -*-
"""转场城市侧闸（2026-11-02 沪→西安 15:38 发车、23:59 抵达案）：
到达城条目不得排进进城交通前的空窗、出发城条目不得排进离城之后。
三层闸 = insertion 主路 / CP solve_day / 兜底顺序排，外加挪日修复的
到达侧（深夜到达日装不下 → 挪同城更晚一天 / 挪不动则移除留痕）。
"""

from datetime import time

from app.services.agent.plan import (
    _fallback_sequence_times,
    _reconcile_transfer_days,
)
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import insertion_schedule_day, solve_day


def _visit(item_id, *, dur=180, day=1, city="西安", **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city=city,
        day=day,
        duration_minutes=dur,
        **kw,
    )


def _train(
    item_id="t1",
    day=1,
    dep=time(15, 38),
    arr=time(23, 59),
    frm="上海",
    to="西安",
) -> TransferItem:
    dur = (arr.hour * 60 + arr.minute) - (dep.hour * 60 + dep.minute)
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=1,
        from_city=frm,
        to_city=to,
        mode="train",
        start_time=dep,
        end_time=arr,
        duration_minutes=dur,
    )


def _plan(days):
    return ItineraryPlan(itinerary_id="it1", cities=["上海", "西安"], days=days)


def _find(day, item_id):
    return next(i for i in day.items if i.item_id == item_id)


# ---------------- insertion 主路 ----------------


def test_insertion_arrival_city_not_before_late_train():
    # 15:38 发车、23:59 抵达：西安条目在当天任何位置都不可行 → 整日无解
    day = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    assert insertion_schedule_day(day, poi_hours=[]) is None


def test_insertion_arrival_city_after_flight():
    # 09:00-12:00 航班/早班火车：西安条目落位须 ≥ 落地时刻（dur=120：
    # 16:30 开场闸下 14:30 落地地板起排仍有窗，可排——深夜到达的
    # 整日降级由 test_insertion_arrival_city_not_before_late_train 覆盖）
    t = _train(dep=time(9, 0), arr=time(12, 0))
    day = DayPlan(day=1, base_city="上海", items=[t, _visit("wall", dur=120)])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    wall = next(i for i in solved.items if isinstance(i, VisitItem))
    assert wall.start_time >= time(12, 0)


def test_insertion_departure_city_not_after_return_train():
    # 返程日（西安→上海 15:10）：上海条目（到达城）落地前不可行
    t = _train(dep=time(15, 10), arr=time(23, 59), frm="西安", to="上海")
    day = DayPlan(
        day=5, base_city="西安", items=[t, _visit("bund", city="上海", dur=90)]
    )
    assert insertion_schedule_day(day, poi_hours=[]) is None


def test_insertion_departure_city_visit_before_return_train_still_ok():
    # 返程日上午的西安条目（出发城、发车前）照旧合法
    t = _train(dep=time(15, 10), arr=time(23, 59), frm="西安", to="上海")
    day = DayPlan(day=5, base_city="西安", items=[t, _visit("huaqing", dur=90)])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    v = next(i for i in solved.items if isinstance(i, VisitItem))
    assert v.end_time <= time(13, 40)  # 发车 -90 缓冲


def test_insertion_no_city_signal_ungated():
    # 城市缺信号（空串）不加码：保持旧口径可排（宁不加码不可错拦）
    day = DayPlan(day=1, base_city="上海", items=[_train(), _visit("m", city="")])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None


def test_insertion_unrelated_city_ungated():
    # 条目城市与该腿两端都不一致（数据口径外）不拦
    day = DayPlan(day=1, base_city="上海", items=[_train(), _visit("hz", city="杭州")])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None


# ---------------- CP solve_day ----------------


def test_cp_arrival_city_not_before_late_train():
    day = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    assert solve_day(day, poi_hours=[]) is None


def test_cp_arrival_city_after_flight():
    # dur=120：同 insertion 测——cap=14:30 恰达落地地板可排
    t = _train(dep=time(9, 0), arr=time(12, 0))
    day = DayPlan(day=1, base_city="上海", items=[t, _visit("wall", dur=120)])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    wall = next(i for i in solved.items if isinstance(i, VisitItem))
    assert wall.start_time >= time(12, 0)


def test_cp_departure_city_not_after_return_train():
    t = _train(dep=time(15, 10), arr=time(23, 59), frm="西安", to="上海")
    day = DayPlan(
        day=5, base_city="西安", items=[t, _visit("bund", city="上海", dur=90)]
    )
    assert solve_day(day, poi_hours=[]) is None


def test_cp_departure_city_visit_before_return_train_still_ok():
    t = _train(dep=time(15, 10), arr=time(23, 59), frm="西安", to="上海")
    day = DayPlan(day=5, base_city="西安", items=[t, _visit("huaqing", dur=90)])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    v = next(i for i in solved.items if isinstance(i, VisitItem))
    assert v.end_time <= time(13, 40)


def test_cp_pinned_arrival_city_iron_rule_19_ungated():
    # 用户钉（铁律 19）优先于排程规则：照旧钉死不判
    w = _visit("wall", start_time=time(9, 0), end_time=time(12, 0), pinned=True)
    day = DayPlan(day=1, base_city="上海", items=[_train(), w])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    wall = next(i for i in solved.items if isinstance(i, VisitItem))
    assert wall.start_time == time(9, 0)


# ---------------- 兜底顺序排 ----------------


def test_fallback_leaves_arrival_city_untimed_on_late_train():
    plan = _plan([DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])])
    _fallback_sequence_times(plan)
    assert _find(plan.days[0], "wall").start_time is None


def test_fallback_arrival_city_after_flight_places():
    # 11-05 结束闸：180 分钟大点 12:00 落地 + 午餐硬窗后开场 13:30 >
    # cap(16:30−180)=13:00 → 排不上；改 90 分钟轻点验证落地后排语义。
    t = _train(dep=time(9, 0), arr=time(12, 0))
    plan = _plan([DayPlan(day=1, base_city="上海", items=[t, _visit("wall", dur=90)])])
    _fallback_sequence_times(plan)
    wall = _find(plan.days[0], "wall")
    assert wall.start_time is not None
    assert wall.start_time >= time(12, 0)


def test_fallback_departure_city_before_return_train_places():
    t = _train(dep=time(15, 10), arr=time(23, 59), frm="西安", to="上海")
    plan = _plan(
        [DayPlan(day=5, base_city="西安", items=[t, _visit("huaqing", dur=90)])]
    )
    _fallback_sequence_times(plan)
    v = _find(plan.days[0], "huaqing")
    assert v.start_time is not None
    assert v.end_time <= time(13, 40)


# ---------------- 挪日修复·到达侧 ----------------


def test_reconcile_moves_arrival_city_visit_to_later_day():
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("terracotta", day=2, dur=90)])
    day3 = DayPlan(day=3, base_city="西安", items=[_visit("museum", day=3, dur=120)])
    plan = _plan([day1, day2, day3])
    notes = _reconcile_transfer_days(plan)
    wall = _find(day2, "wall")
    assert wall.day == 2
    assert wall.start_time is None
    assert all(i.item_id != "wall" for i in day1.items)
    assert any("进城" in str(n) or "inbound" in str(n) for n in notes)


def test_reconcile_skips_full_later_day_when_hosting():
    # day2 已满（容量口径装不下 180 分钟）→ 挪去 day3
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("a", day=2, dur=180),
            _visit("b", day=2, dur=180),
            _visit("c", day=2, dur=210),
        ],
    )
    day3 = DayPlan(day=3, base_city="西安", items=[_visit("m", day=3, dur=120)])
    plan = _plan([day1, day2, day3])
    _reconcile_transfer_days(plan)
    wall = next(i for d in plan.days for i in d.items if i.item_id == "wall")
    assert wall.day == 3


def test_reconcile_drops_arrival_city_visit_when_no_host():
    # 单日行程（上海→西安）无更晚同城日 → 移除留痕
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    plan = _plan([day1])
    notes = _reconcile_transfer_days(plan)
    assert all(i.item_id != "wall" for i in day1.items)
    assert any("移除" in str(n) or "removed" in str(n) for n in notes)


def test_reconcile_protected_must_relocates_to_host_day():
    # 2026-11-07「放其它日期早晨」拍板：必去挂在到达日装不下 → 先挪
    # 同城后续天（在册不删），不再只披露换天
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("t", day=2, dur=90)])
    plan = _plan([day1, day2])
    notes = _reconcile_transfer_days(plan, protect=frozenset({"wall"}))
    assert _find(day2, "wall").day == 2
    assert any("已挪至第2天" in str(n) for n in notes)


def test_reconcile_protects_must_visit_no_host_discloses():
    # 无更晚同城日（单日行程）→ 原地保留 + 披露换天（铁律 19 不删）
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    plan = _plan([day1])
    notes = _reconcile_transfer_days(plan, protect=frozenset({"wall"}))
    assert _find(day1, "wall").day == 1
    assert any("必去" in str(n) or "Must-visits" in str(n) for n in notes)


def test_reconcile_keeps_flight_day_arrival_visit():
    # 12:00 落地、90 分钟条目落地后装得下 → 不挪（回归闸：白天的
    # 航班进城日旧行为不受影响；180 分钟大点在 11-05 结束闸下
    # 16:30−180=13:00 开场地板装不下 → 挪日，见 moves 用例）
    t = _train(dep=time(9, 0), arr=time(12, 0))
    day1 = DayPlan(day=1, base_city="上海", items=[t, _visit("wall", dur=90)])
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("t2", day=2, dur=90)])
    plan = _plan([day1, day2])
    _reconcile_transfer_days(plan)
    assert _find(day1, "wall").day == 1


def test_reconcile_clears_pre_arrival_time_when_room():
    # 时刻被排在抵达前（旧引擎/编辑路径产物）但当天落地后装得下 →
    # 清时刻交排程器重排（条目留在当天）
    t = _train(dep=time(9, 0), arr=time(12, 0))
    w = _visit("wall", dur=90, start_time=time(8, 0), end_time=time(11, 0))
    day1 = DayPlan(day=1, base_city="上海", items=[t, w])
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("t2", day=2, dur=90)])
    plan = _plan([day1, day2])
    _reconcile_transfer_days(plan)
    wall = _find(day1, "wall")
    assert wall.day == 1
    assert wall.start_time is None


def test_reconcile_departure_side_still_works():
    # 离城侧既有语义回归：上海条目在离城日装不下早晨 → 挪更早的上海日
    t = _train(dep=time(15, 38), arr=time(23, 59))
    day1 = DayPlan(
        day=1, base_city="上海", items=[_visit("sh1", city="上海", day=1, dur=90)]
    )
    day2 = DayPlan(
        day=2, base_city="上海", items=[t, _visit("sh2", city="上海", day=2, dur=360)]
    )
    plan = _plan([day1, day2])
    notes = _reconcile_transfer_days(plan)
    moved = next((i for i in day1.items if i.item_id == "sh2"), None)
    assert moved is not None
    assert moved.day == 1
    assert any("离城" in str(n) or "outbound" in str(n) for n in notes)
