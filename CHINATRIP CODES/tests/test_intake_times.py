# -*- coding: utf-8 -*-
"""行前信息（2026-11-14 用户拍板）：每次规划需求先核对出发日期、行程日期是否
覆盖到达日/离开日，覆盖就要航班·车次或当地到达/离开时刻。

本文件守的是「拿到时刻之后真的落位」这一段：
- `_parse_hm` / `_shift_hm` 只认 24 小时制写法、非法输入一律当没填；
- 去程到达时刻写回最早一天的城际腿（按腿时长反推发车/起飞时刻）；
- 返程离开时刻写回最晚一天的城际腿；
- 落位成不了一律只写一条披露，不抛异常（行程照常交付）。
"""

import asyncio
from datetime import time

from app.services.agent.plan import (
    DayPlan,
    ItineraryPlan,
    PlanningAgent,
    PlanSession,
    TransferItem,
    _parse_hm,
    _shift_hm,
)


class _NoLLM:
    """本文件只测落位，不该有 LLM 调用。"""

    name = "none"

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("LLM must not be called by intake landing")


def _plan() -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-intake",
        cities=["上海", "杭州"],
        days=[
            DayPlan(
                day=1,
                base_city="上海",
                items=[
                    TransferItem(
                        item_id="t1",
                        day=1,
                        seq=1,
                        from_city="上海",
                        to_city="杭州",
                        mode="train",
                        start_time=time(9, 0),
                        end_time=time(10, 30),
                        duration_minutes=90,
                        train_no="G7501",
                    )
                ],
            ),
            DayPlan(day=2, base_city="杭州"),
            DayPlan(
                day=3,
                base_city="杭州",
                items=[
                    TransferItem(
                        item_id="t2",
                        day=3,
                        seq=1,
                        from_city="杭州",
                        to_city="上海",
                        mode="train",
                        start_time=time(18, 0),
                        end_time=time(19, 30),
                        duration_minutes=90,
                        train_no="G7598",
                    )
                ],
            ),
        ],
    )


def _session(**kwargs) -> PlanSession:
    return PlanSession(
        session_id="s-intake",
        device_id="device-1",
        cities=["上海", "杭州"],
        days=3,
        plan=_plan(),
        **kwargs,
    )


# --- 解析 -------------------------------------------------------------------


def test_parse_hm_accepts_common_forms() -> None:
    assert _parse_hm("14:30") == time(14, 30)
    assert _parse_hm(" 9:05 ") == time(9, 5)
    assert _parse_hm("14：30") == time(14, 30)
    assert _parse_hm("14.30") == time(14, 30)


def test_parse_hm_rejects_junk_and_out_of_range() -> None:
    for bad in [None, "", "abc", "24:00", "12:60", "1430", "14:3"]:
        assert _parse_hm(bad) is None


def test_shift_hm_clamps_inside_the_day() -> None:
    assert _shift_hm(time(14, 30), -90) == time(13, 0)
    assert _shift_hm(time(0, 30), -90) == time(0, 0)
    assert _shift_hm(time(23, 30), 90) == time(23, 59)


# --- 落位 -------------------------------------------------------------------


def test_arrival_and_departure_times_land_on_the_right_legs() -> None:
    session = _session(arrival_time="14:30", departure_time="16:00")
    asyncio.run(PlanningAgent(_NoLLM())._apply_intake_times(session))

    outbound = session.plan.days[0].items[0]
    assert outbound.end_time == time(14, 30)  # 当地落地
    assert outbound.start_time == time(13, 0)  # 90 分钟车程反推
    assert outbound.duration_minutes == 90

    inbound = session.plan.days[2].items[0]
    assert inbound.start_time == time(16, 0)  # 当地起飞/发车
    assert inbound.end_time == time(17, 30)

    joined = " ".join(session.assumptions)
    assert "到达" in joined and "14:30" in joined
    assert "离开" in joined and "16:00" in joined


def test_no_intake_info_relaxes_to_full_days() -> None:
    """到达/离开的班次与时刻都没填：撤掉对应天的城际腿，按全天游玩规划
    （2026-11-14 拍板「不填默认全天都可以规划」）。"""
    session = _session(intake_done=True)  # 行前卡 opting-in：没填 → 全天放宽
    asyncio.run(PlanningAgent(_NoLLM())._apply_intake_times(session))

    assert not [
        i for d in session.plan.days for i in d.items if isinstance(i, TransferItem)
    ]
    joined = " ".join(session.assumptions)
    assert "第1天" in joined and "全天" in joined
    assert "第3天" in joined and "全天" in joined


def test_unparseable_time_counts_as_unfilled() -> None:
    """时刻写法读不出（「下午两点」）按未填处理：到达/离开两侧都走全天放宽。"""
    session = _session(arrival_time="下午两点", intake_done=True)
    asyncio.run(PlanningAgent(_NoLLM())._apply_intake_times(session))
    assert not [
        i for d in session.plan.days for i in d.items if isinstance(i, TransferItem)
    ]
    joined = " ".join(session.assumptions)
    assert "第1天" in joined and "全天" in joined


def test_single_leg_trip_pins_the_outbound_only() -> None:
    plan = _plan()
    plan.days = [d for d in plan.days if d.day != 3]
    plan.days[0] = plan.days[0].model_copy(deep=True)
    session = PlanSession(
        session_id="s-one-way",
        device_id="device-1",
        cities=["上海", "杭州"],
        days=2,
        plan=plan,
        arrival_time="11:45",
        departure_time="16:00",  # 没有返程腿：不炸、不编一条出来
    )
    asyncio.run(PlanningAgent(_NoLLM())._apply_intake_times(session))
    assert session.plan.days[0].items[0].end_time == time(11, 45)
    assert len(session.plan.days) == 2


def test_one_city_plan_absorbs_arrival_time_via_synthetic_leg() -> None:
    """单城行程没有城际腿：到达时刻也要被吸收——补一条合成到达腿，当天
    非钉景点清时刻重排到到达之后（用户实报「时刻没被 PLANNING ENGINE
    吸收」的根因）。"""
    from app.services.itinerary import VisitItem

    plan = ItineraryPlan(
        itinerary_id="it-one-city",
        cities=["西安"],
        days=[
            DayPlan(
                day=1,
                base_city="西安",
                items=[
                    VisitItem(
                        item_id="v1",
                        name="钟楼",
                        city="西安",
                        category="sight",
                        day=1,
                        duration_minutes=90,
                        start_time=time(9, 0),
                        end_time=time(10, 30),
                    )
                ],
            ),
            DayPlan(day=2, base_city="西安"),
        ],
    )
    session = PlanSession(
        session_id="s-one-city",
        device_id="device-1",
        cities=["西安"],
        days=2,
        plan=plan,
        start_date="2026-11-16",
        arrival_time="15:30",
    )
    asyncio.run(PlanningAgent(_NoLLM())._apply_intake_times(session))

    legs = [
        i for d in session.plan.days for i in d.items if isinstance(i, TransferItem)
    ]
    assert len(legs) == 1 and legs[0].end_time == time(15, 30)
    assert legs[0].to_city == "西安"
    # 到达之前的旧时刻必须被清掉：当天不再有 15:30 之前的观光件
    # （装不下的由引擎顺延到更晚的一天，_reconcile_transfer_days 口径）
    assert not [
        i
        for i in session.plan.days[0].items
        if isinstance(i, VisitItem)
        and i.start_time is not None
        and i.start_time < time(15, 30)
    ]
    assert any("15:30" in a for a in session.assumptions)


def test_no_info_on_one_city_plan_changes_nothing() -> None:
    """单城行程没填到达/离开：没有腿可撤、也没有腿可造——零改动零噪音。"""
    from app.services.itinerary import VisitItem

    plan = ItineraryPlan(
        itinerary_id="it-quiet",
        cities=["西安"],
        days=[
            DayPlan(
                day=1,
                base_city="西安",
                items=[
                    VisitItem(
                        item_id="v1",
                        name="钟楼",
                        city="西安",
                        category="sight",
                        day=1,
                        duration_minutes=90,
                        start_time=time(9, 0),
                        end_time=time(10, 30),
                    )
                ],
            )
        ],
    )
    session = PlanSession(
        session_id="s-quiet",
        device_id="device-1",
        cities=["西安"],
        days=1,
        plan=plan,
    )
    before = session.plan.model_dump()
    asyncio.run(PlanningAgent(_NoLLM())._apply_intake_times(session))
    assert session.plan.model_dump() == before
    assert session.assumptions == []


def test_arrival_date_targets_its_day() -> None:
    """到达日期不等于出发日期：按日期换算到对应天序落位。"""
    session = _session(arrival_date="2026-11-17", arrival_time="14:00")
    session.plan = session.plan.model_copy(update={"start_date": "2026-11-16"})
    asyncio.run(PlanningAgent(_NoLLM())._apply_intake_times(session))

    legs = {
        d.day: [i for i in d.items if isinstance(i, TransferItem)]
        for d in session.plan.days
    }
    # 到达信息给了（目标是第 2 天）→ 第 2 天合成腿；第 1 天的腿保持 v0 原样
    assert legs[1] and legs[1][0].end_time == time(10, 30)
    assert legs[2] and legs[2][0].end_time == time(14, 0)
    assert any("第2天" in a and "14:00" in a for a in session.assumptions)


def test_number_not_found_falls_back_to_user_time() -> None:
    """班次号查不到 + 用户把时刻从默认改掉：该时刻=运输腿到达/离开时刻，
    回退按时刻落位（2026-11-14 用户口径），不再静默丢弃。"""
    session = _session(arrival_no="XX888", arrival_time="15:30")
    asyncio.run(PlanningAgent(_NoLLM())._apply_intake_times(session))
    outbound = session.plan.days[0].items[0]
    assert outbound.end_time == time(15, 30)
    joined = " ".join(session.assumptions)
    assert "XX888" in joined and "15:30" in joined
