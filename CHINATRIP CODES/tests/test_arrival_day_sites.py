# -*- coding: utf-8 -*-
"""到达日有安排（2026-11-02「第1天无安排」事故回归 → 2026-11-03 再
收口）：午后落地（06:09→13:20 车次）+150 地板把最早开游推到 15:50。
11-02 曾以「转场日收口闸让位」保到达日有安排——11-03 用户重申（第1天
城墙 18:43 排期事故）：白天景点受入场闸、到达日同闸，装不下
挪日（_reconcile 容量预筛闸前起点预算 + _transfer_day_sweep 清算），
不在傍晚硬排。**2026-11-07 用户再拍板（第 5 次重述）**：闸回归
**开场闸**且收紧到 16:00——观光须 16:00 前安排（开场），时长可以
自然跨过 16:00（营业窗+日终 21:30 照卡）；11-05 的「结束闸=开场+
时长≤16:30」口径作废（它把 240min 级大块头压成必须上午整块开场，
环球中心类下午档结构性无解）。13:20 落地日起排 15:50：60' 轻点
15:50-16:50 合法（跨界收尾），90'+ 大点越 15:30 开场带照旧挪日。
"""

from datetime import time

from app.services.agent.plan import (
    _drop_untimed_visits,
    _reconcile_transfer_days,
    _transfer_day_sweep,
)
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    PoiHours,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import (
    generic_entry_cap,
    insertion_schedule_day,
    solve_day,
)


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
    dep=time(6, 9),
    arr=time(13, 20),
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


# ---------------- 白闸开场口径（solver 层，2026-11-03） ----------------


def test_generic_entry_cap_start_based_all_days():
    # 2026-11-17 拍板：闸=开场闸 16:30（时长可跨界收尾，营业窗+日终
    # 照卡）；大点 15:30 开场带并列上限。开放形态豁免在删除层执行。
    light = _visit("stroll", dur=60)
    w = PoiHours(poi_id="stroll", opens=time(9, 0), closes=time(21, 0))
    assert generic_entry_cap(light, w) == 16 * 60 + 30
    assert generic_entry_cap(light, None) == 16 * 60 + 30
    big = _visit("wall", dur=120)
    wb = PoiHours(poi_id="wall", opens=time(9, 0), closes=time(21, 0))
    assert generic_entry_cap(big, wb) == 930
    assert generic_entry_cap(big, None) == 930


def test_arrival_day_wall_not_placed_after_gate():
    # 13:20 落地 +120 地板（火车 2h，2026-11-14）= 15:20 起排；2026-11-07 开场闸 16:00：
    # 60' 轻点 15:20 开场合法（16:50 跨界收尾）；120'/330' 大点越
    # 15:30 开场带 → 整日降级（挪日）。
    short = DayPlan(day=1, base_city="上海", items=[_train(), _visit("x", dur=60)])
    solved = solve_day(short, poi_hours=[])
    assert solved is not None
    stroll = next(i for i in solved.items if isinstance(i, VisitItem) and i.name == "x")
    assert stroll.start_time == time(15, 20)
    # 120' 大点 15:20 开场合法（≤15:30 大点带，17:20 跨界收尾）；
    # 330' 也不再判死：日终 21:00 前收得住（15:20+330=20:50），大点带只管开场
    for dur in (120, 330):
        day = DayPlan(day=1, base_city="上海", items=[_train(), _visit("x", dur=dur)])
        solved_d = solve_day(day, poi_hours=[])
        assert solved_d is not None
        got = next(
            i for i in solved_d.items if isinstance(i, VisitItem) and i.name == "x"
        )
        assert got.start_time == time(15, 20)
    long_day = DayPlan(
        day=1, base_city="上海", items=[_train(), _visit("wall", dur=330)]
    )
    # 插入主路更严（入场闸+窗整段校验）→ 330' 仍判当天装不下
    assert insertion_schedule_day(long_day, poi_hours=[]) is None


def test_cp_midday_arrival_places_before_start_gate():
    # 13:20 落地 → 地板 15:20；2026-11-07 开场闸 16:00：60' 轻点
    # 15:20 开场合法（跨界收尾）——到达日午后不再一律降级。
    day = DayPlan(day=1, base_city="上海", items=[_train(), _visit("stroll", dur=60)])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    stroll = next(
        i for i in solved.items if isinstance(i, VisitItem) and i.name == "stroll"
    )
    assert stroll.start_time == time(15, 20)


def test_insertion_midday_arrival_places_before_start_gate():
    day = DayPlan(day=1, base_city="上海", items=[_train(), _visit("stroll", dur=60)])
    assert insertion_schedule_day(day, poi_hours=[]) is not None


def test_cp_midday_arrival_respects_hours_close():
    # 让位≠放飞：17:00 闭馆的馆 15:50 开游 120 分钟物理装不下 → 整日无解
    wall = _visit("wall", dur=120, poi_id="wall")
    day = DayPlan(day=1, base_city="上海", items=[_train(), wall])
    hours = [PoiHours(poi_id="wall", opens=time(9, 0), closes=time(17, 0))]
    assert solve_day(day, poi_hours=hours) is None


def test_cp_normal_day_cap_still_binds():
    # 回归闸：无转场腿的普通日——2026-11-07 开场闸 16:00：90 分钟点
    # （大点 15:30 带）最晚 15:30 开场，跨界收尾合法。
    day = DayPlan(day=1, base_city="西安", items=[_visit("wall", dur=90)])
    hours = [PoiHours(poi_id="wall", opens=time(9, 0), closes=time(21, 0))]
    solved = solve_day(day, poi_hours=hours)
    assert solved is not None
    wall = next(i for i in solved.items if isinstance(i, VisitItem))
    m = wall.start_time.hour * 60 + wall.start_time.minute
    assert m <= 930


# ---------------- 挪日修复·容量预筛 ----------------


def test_reconcile_midday_arrival_moves_all_under_end_gate():
    # 13:20 落地窗 [15:50, 21:30]；2026-11-17 开场闸 16:30：
    # 60' 轻点 15:20 开场合法（留 day1）；90' 大点（挂受限营业窗=
    # 封闭景点口径）越 15:30 开场带 → v2/v3 挪 day2。无窗=开放形态
    # 豁免不挪（2026-11-17），故 v2/v3 必须带窗才能保住挪日语义。
    day1 = DayPlan(
        day=1,
        base_city="上海",
        items=[
            _train(),
            _visit("v1", dur=60),
            _visit(
                "v2",
                dur=90,
                poi_id="v2",
                opening_hours="周一至周日 09:00-18:00",
            ),
            _visit(
                "v3",
                dur=90,
                poi_id="v3",
                opening_hours="周一至周日 09:00-18:00",
            ),
        ],
    )
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("t", day=2, dur=90)])
    plan = _plan([day1, day2])
    notes = _reconcile_transfer_days(plan)
    stays = [v.item_id for v in day1.items if isinstance(v, VisitItem)]
    assert stays == ["v1"]
    moved_ids = sorted(
        i.item_id for d in plan.days for i in d.items if i.item_id in ("v2", "v3")
    )
    assert moved_ids == ["v2", "v3"]
    assert all(
        next(i for d in plan.days for i in d.items if i.item_id == vid).day == 2
        for vid in ("v2", "v3")
    )
    assert any("进城" in str(n) or "inbound" in str(n) for n in notes)


def test_reconcile_capacity_moves_whole_arrival_batch():
    # 到达日容量收口已并入 _transfer_day_sweep：C 容量装不下的整组挪同城
    # 更晚一天（2026-11-12 起「先挪日」），不再按 tier 就地裁汰；
    # 本用例锁「不静默丢件」这个不变式。
    day1 = DayPlan(
        day=1,
        base_city="上海",
        items=[
            _train(),
            _visit("big", dur=90, best_visit_time="evening"),
            _visit("small", dur=90, best_visit_time="evening"),
            _visit("extra", dur=90, best_visit_time="evening"),
        ],
    )
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("t", day=2, dur=90)])
    plan = _plan([day1, day2])
    _transfer_day_sweep(plan, frozenset(), {"big": 1, "small": 1, "extra": 9})
    for vid in ("big", "small", "extra"):
        moved = next(i for d in plan.days for i in d.items if i.item_id == vid)
        assert moved.day == 2, "到达日装不下 → 整组挪同城次日，不静默丢"


def test_reconcile_hours_close_moves_to_later_day():
    # 落地后闭馆装不下（15:20 开游 90' 进 17:00 闭馆）→ 不留当天等
    # None-None 卡，直接挪 day2
    # 15:20 落地起排 + 120' 会压过 17:00 闭馆（90' 恰好收在 16:50，装得下）
    w = _visit("museum", dur=120, poi_id="museum", opening_hours="09:00-17:00")
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), w])
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("t", day=2, dur=90)])
    plan = _plan([day1, day2])
    _reconcile_transfer_days(plan)
    moved = next(i for d in plan.days for i in d.items if i.item_id == "museum")
    assert moved.day == 2


# ---------------- 转场日无时刻清算 ----------------


def test_sweep_moves_arrival_side_stray():
    # 兜底排不上时刻的到达城条目 → 挪同城更晚一天（None-NOne 卡不留）
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("t", day=2, dur=90)])
    plan = _plan([day1, day2])
    notes = _transfer_day_sweep(plan)
    wall = _find(day2, "wall")
    assert wall.day == 2
    assert all(i.item_id != "wall" for i in day1.items)
    assert any("挪至" in str(n) or "moved to day" in str(n) for n in notes)


def test_sweep_moves_departure_side_stray():
    # 出发城条目排不上 → 挪同城更早一天
    t = _train(day=2, dep=time(15, 38), arr=time(23, 59))
    day1 = DayPlan(
        day=1, base_city="上海", items=[_visit("sh1", city="上海", day=1, dur=90)]
    )
    sh2 = _visit("sh2", city="上海", day=2)
    day2 = DayPlan(day=2, base_city="上海", items=[t, sh2])
    plan = _plan([day1, day2])
    notes = _transfer_day_sweep(plan)
    moved = _find(day1, "sh2")
    assert moved.day == 1
    assert any("挪至" in str(n) or "moved to day" in str(n) for n in notes)


def test_sweep_removes_stray_when_no_host():
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), _visit("wall")])
    plan = _plan([day1])
    notes = _transfer_day_sweep(plan)
    assert all(i.item_id != "wall" for i in day1.items)
    assert any("移除" in str(n) or "removed" in str(n) for n in notes)


def test_sweep_discloses_pinned_untimed_only():
    # pinned 铁律 19：不动只披露
    w = _visit("wall", pinned=True)
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), w])
    day2 = DayPlan(day=2, base_city="西安", items=[_visit("t", day=2, dur=90)])
    plan = _plan([day1, day2])
    notes = _transfer_day_sweep(plan)
    assert _find(day1, "wall").day == 1
    assert any("必去" in str(n) or "Must-visits" in str(n) for n in notes)


def test_sweep_skips_days_without_timed_transfers():
    # 普通日的无时刻条目不归清算管（另有排程主路/降级披露）
    day1 = DayPlan(day=1, base_city="西安", items=[_visit("wall")])
    plan = _plan([day1])
    assert _transfer_day_sweep(plan) == []
    assert _find(day1, "wall").day == 1


# ---------------- 终局兜底 ----------------


def test_drop_untimed_removes_notes_keeps_pinned():
    # 重解后仍无时刻 → 移除留痕；pinned 铁律 19 不动
    stray = _visit("stray", day=2)
    pinned = _visit("keep", day=2, pinned=True)
    day2 = DayPlan(day=2, base_city="西安", items=[stray, pinned])
    plan = _plan([day2])
    notes = _drop_untimed_visits(plan)
    assert all(i.item_id != "stray" for i in day2.items)
    assert _find(day2, "keep").day == 2
    assert any("移除" in str(n) or "removed" in str(n) for n in notes)


def test_drop_untimed_ignores_food_and_timed():
    meal = _visit("lunch", day=2, category="food")
    timed = _visit("ok", day=2, start_time=time(9, 0), end_time=time(10, 0))
    day2 = DayPlan(day=2, base_city="西安", items=[meal, timed])
    plan = _plan([day2])
    assert _drop_untimed_visits(plan) == []
    assert len(day2.items) == 2


# ---------------- 铁律 19：protect 名册（必去/心愿）不删 ----------------


def test_sweep_protects_must_names():
    # 2026-11-02 链接必到案：必去 pinned=False（钉在 solve 之后才打），
    # 转场清算曾当杂卡删空——protect 名册内的条目挪不动也只留卡披露
    w = _visit("mustsee")
    day1 = DayPlan(day=1, base_city="上海", items=[_train(), w])
    plan = _plan([day1])
    notes = _transfer_day_sweep(plan, {"mustsee"})
    assert _find(day1, "mustsee").day == 1
    assert any("必去" in str(n) or "Must-visits" in str(n) for n in notes)


def test_drop_untimed_protects_must_names():
    day1 = DayPlan(day=1, base_city="上海", items=[_visit("keep"), _visit("gone")])
    plan = _plan([day1])
    _drop_untimed_visits(plan, {"keep"})
    assert _find(day1, "keep").day == 1
    assert all(i.item_id != "gone" for i in day1.items)
