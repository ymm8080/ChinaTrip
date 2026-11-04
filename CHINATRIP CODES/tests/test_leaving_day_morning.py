# -*- coding: utf-8 -*-
"""离城日上午闸（2026-11-03 拍板「LEAVING DATE IF TRAIN/BUS/FLIGHT IS IN
THE AFTERNOON OR NIGHT, ARRANGE SITES IN THE MORNING BY DEFAULT / NO
ARRANGEMENT」）：火车/大巴/飞机 ≥12:00 发车的离城日，出发城条目一律
上午收尾（end ≤ min(12:00, 发车−90)），午后留白赶车；<12:00（上午）
发车整日无安排——装不下交挪日链，不硬排。汽车腿时刻弹性不设闸；
用户钉与餐/酒店铁律 19 豁免。
"""

from datetime import time

from app.services.agent.plan import (
    _fallback_sequence_times,
    _reconcile_transfer_days,
)
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    PoiHours,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import (
    _leaving_morning_cap,
    insertion_schedule_day,
    solve_day,
)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _visit(item_id, *, dur=90, day=1, city="西安", **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city=city,
        day=day,
        duration_minutes=dur,
        **kw,
    )


def _leg(
    dep=time(17, 0),
    arr=time(20, 0),
    frm="西安",
    to="上海",
    mode="train",
    item_id="t1",
    day=1,
) -> TransferItem:
    dur = _minutes(arr) - _minutes(dep)
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=1,
        from_city=frm,
        to_city=to,
        mode=mode,
        start_time=dep,
        end_time=arr,
        duration_minutes=dur,
    )


def _plan(days):
    return ItineraryPlan(itinerary_id="it1", cities=["上海", "西安"], days=days)


# ---------------- 闸值口径 ----------------


def test_leaving_morning_cap_matrix():
    # 汽车=弹性时刻不设闸；火车/大巴/飞机 ≥12:00 发车=min(12:00, 发车−90)；
    # <12:00 发车=日始（必令出发城条目不可行=整日无安排）
    assert _leaving_morning_cap("car", 17 * 60) is None
    assert _leaving_morning_cap(None, 17 * 60) is None
    assert _leaving_morning_cap("train", 13 * 60) == 11 * 60 + 30  # 发车−90
    assert _leaving_morning_cap("train", 17 * 60) == 12 * 60  # 正午收口
    assert _leaving_morning_cap("flight", 20 * 60) == 12 * 60
    assert _leaving_morning_cap("bus", 15 * 60) == 12 * 60
    assert _leaving_morning_cap("train", 11 * 60 + 45) == 9 * 60  # 无安排


# ---------------- 求解器层（插入主路 + CP 兜底） ----------------


def test_afternoon_train_sites_end_by_noon_insertion():
    # 17:00 发车：两个 90 分钟点全部上午收尾（9:00-10:30、10:30-12:00），
    # 午后整段留白
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_leg(), _visit("v1", dur=90), _visit("v2", dur=90)],
    )
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    ends = sorted(
        _minutes(i.end_time) for i in solved.items if isinstance(i, VisitItem)
    )
    assert ends == [10 * 60 + 30, 12 * 60]


def test_afternoon_train_sites_end_by_noon_cp():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_leg(), _visit("v1", dur=90), _visit("v2", dur=90)],
    )
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    for i in solved.items:
        if isinstance(i, VisitItem):
            assert _minutes(i.end_time) <= 12 * 60


def test_night_flight_sites_end_by_noon():
    # 20:00 夜航同样上午收尾——不往「发车−90」的傍晚空档里塞点
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _leg(dep=time(20, 0), arr=time(23, 0), mode="flight"),
            _visit("v1", dur=120),
        ],
    )
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    v1 = next(i for i in solved.items if isinstance(i, VisitItem))
    assert _minutes(v1.start_time) == 9 * 60
    assert _minutes(v1.end_time) == 11 * 60


def test_early_afternoon_train_cap_is_dep_minus_buffer():
    # 13:00 发车：min(12:00, 发车−90)=11:30 收尾（发车缓冲先咬）
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_leg(dep=time(13, 0), arr=time(16, 0)), _visit("v1", dur=120)],
    )
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    v1 = next(i for i in solved.items if isinstance(i, VisitItem))
    assert _minutes(v1.end_time) <= 11 * 60 + 30


def test_morning_train_no_arrangement():
    # 11:45（上午）发车：旧口径 9:00-10:00 贴缓冲可排，拍板后整日无安排
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_leg(dep=time(11, 45), arr=time(14, 45)), _visit("v1", dur=60)],
    )
    assert insertion_schedule_day(day, poi_hours=[]) is None
    assert solve_day(day, poi_hours=[]) is None


def test_bus_departure_gated_like_train():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _leg(dep=time(15, 0), arr=time(18, 0), mode="bus"),
            _visit("v1", dur=90),
        ],
    )
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    v1 = next(i for i in solved.items if isinstance(i, VisitItem))
    assert _minutes(v1.end_time) <= 12 * 60


def test_car_departure_afternoon_visit_allowed():
    # 汽车腿时刻弹性不设上午闸：营业窗只开午后的馆照排（对比火车同窗必挪）
    hours = [PoiHours(poi_id="v1", opens=time(13, 0), closes=time(15, 0))]
    car_day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _leg(dep=time(16, 0), arr=time(18, 0), mode="car"),
            _visit("v1", dur=90, poi_id="v1"),
        ],
    )
    solved = insertion_schedule_day(car_day, poi_hours=hours)
    assert solved is not None
    v1 = next(i for i in solved.items if isinstance(i, VisitItem))
    assert (v1.start_time, v1.end_time) == (time(13, 0), time(14, 30))
    train_day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _leg(dep=time(16, 0), arr=time(18, 0)),
            _visit("v1", dur=90, poi_id="v1"),
        ],
    )
    assert insertion_schedule_day(train_day, poi_hours=hours) is None


def test_pinned_afternoon_visit_keeps_time_iron_rule_19():
    # 用户钉住的午后点=用户安排，铁律 19 不动
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _leg(),
            _visit(
                "v_pin",
                dur=90,
                pinned=True,
                start_time=time(14, 0),
                end_time=time(15, 30),
            ),
        ],
    )
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    pin = next(i for i in solved.items if i.item_id == "v_pin")
    assert (pin.start_time, pin.end_time) == (time(14, 0), time(15, 30))


# ---------------- plan 兜底顺序排 ----------------


def test_fallback_leaving_day_visit_morning_only():
    # 降级兜底同口径：17:00 发车，90 分钟点排 9:00-10:30；240 分钟点
    # 上午装不下→留空交挪日链，不塞午后
    plan = _plan(
        [
            DayPlan(
                day=1,
                base_city="西安",
                items=[_leg(), _visit("v_fit", dur=90), _visit("v_big", dur=240)],
            )
        ]
    )
    _fallback_sequence_times(plan)
    day = plan.days[0]
    fit = next(i for i in day.items if i.item_id == "v_fit")
    big = next(i for i in day.items if i.item_id == "v_big")
    assert (fit.start_time, fit.end_time) == (time(9, 0), time(10, 30))
    assert big.start_time is None


# ---------------- 挪日修复·容量预筛（_reconcile_transfer_days） ----------------


def test_reconcile_afternoon_flight_moves_oversized_to_earlier_day():
    # 17:00 航班：上午窗 180'，240 分钟大点装不下→挪前一天（旧口径
    # dep−90−9:00=390' 能塞下且常被排进午后——即本拍板靶形）
    day1 = DayPlan(day=1, base_city="西安", items=[_visit("warm", day=1, dur=90)])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _leg(dep=time(17, 0), arr=time(19, 30), mode="flight", day=2),
            _visit("big", day=2, dur=240),
        ],
    )
    plan = _plan([day1, day2])
    notes = _reconcile_transfer_days(plan)
    big = next(i for d in plan.days for i in d.items if i.item_id == "big")
    assert big.day == 1
    assert any("离城" in str(n) or "outbound" in str(n) for n in notes)


def test_reconcile_morning_departure_no_arrangement():
    # 11:45 发车（上午）=整日无安排：短点也挪走
    day1 = DayPlan(day=1, base_city="西安", items=[])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _leg(dep=time(11, 45), arr=time(14, 45), day=2),
            _visit("v", day=2, dur=60),
        ],
    )
    plan = _plan([day1, day2])
    _reconcile_transfer_days(plan)
    moved = next((i for d in plan.days for i in d.items if i.item_id == "v"), None)
    assert moved is not None and moved.day == 1


def test_reconcile_stale_afternoon_time_cleared_not_evicted():
    # 挪进离城日的旧时刻（13:00 收尾 > 12:00 闸）不再按搁浅驱逐整卡——
    # 清时刻交 solve/fallback 按上午闸重排（用户点名「挪到最后一天」
    # 与引擎意志对撞事故，2026-11-03 收口）；90 分钟上午装得下 → 留天。
    day1 = DayPlan(day=1, base_city="西安", items=[])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _leg(day=2),
            _visit(
                "v_pm",
                day=2,
                dur=90,
                start_time=time(13, 0),
                end_time=time(14, 30),
            ),
        ],
    )
    plan = _plan([day1, day2])
    _reconcile_transfer_days(plan)
    vpm = next(i for d in plan.days for i in d.items if i.item_id == "v_pm")
    assert vpm.day == 2  # 物理装得下：留天重排，不驱逐
    assert vpm.start_time is None and vpm.end_time is None


def test_reconcile_user_edit_keeps_timed_afternoon_visit():
    # 用户权威路径（move/retime/replace 端点，铁律 19）：旧口径容量+
    # 不清时刻——用户亲手摆的 13:00 卡原样保留。
    day1 = DayPlan(day=1, base_city="西安", items=[])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _leg(day=2),
            _visit(
                "v_user",
                day=2,
                dur=90,
                start_time=time(13, 0),
                end_time=time(14, 30),
            ),
        ],
    )
    plan = _plan([day1, day2])
    _reconcile_transfer_days(plan, user_edit=True)
    v = next(i for d in plan.days for i in d.items if i.item_id == "v_user")
    assert v.day == 2
    assert v.start_time == time(13, 0) and v.end_time == time(14, 30)


def test_reconcile_food_stays_on_leaving_day():
    # 餐件跟餐窗走不进搁浅逻辑（2026-11-01 口径不变）
    day1 = DayPlan(day=1, base_city="西安", items=[])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _leg(day=2),
            _visit(
                "lunch",
                day=2,
                dur=90,
                category="food",
                start_time=time(12, 0),
                end_time=time(13, 30),
            ),
        ],
    )
    plan = _plan([day1, day2])
    _reconcile_transfer_days(plan)
    lunch = next(i for d in plan.days for i in d.items if i.item_id == "lunch")
    assert lunch.day == 2 and lunch.start_time == time(12, 0)
