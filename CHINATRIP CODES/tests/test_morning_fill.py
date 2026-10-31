# -*- coding: utf-8 -*-
"""2026-10-31 上午空排事故回归：

1. 演出真场次（show_sessions 管线写入 opening_hours）→ solver 按场次
   开窗，不再吃 S5 晚场硬窗（3 演出同日不再被塞同一个 35 分钟晚窗）。
2. solve_plan 按日降级：坏日原样保留，好日保住解。
3. 兜底排列三修正：餐位 0 缓冲（180 分钟可落 9:00-12:00）、失败不
   推进游标（短条目回填空窗）、无场次晚场演出不进上午。
4. _morning_fill 上午保底：空白上午补候选点，雨天只收室内。
"""

from datetime import time

from app.services.agent.plan import (
    PlanningAgent,
    _fallback_sequence_times,
    _morning_occupied,
)
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import (
    show_session_starts,
    solve_day,
)


class _NoLLM:
    async def chat(self, *a, **k):  # pragma: no cover - 不应被调用
        raise AssertionError("llm must not be called")


def _visit(item_id, *, dur=60, day=1, city="西安", **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city=city,
        day=day,
        duration_minutes=dur,
        **kw,
    )


def _lunch(day=1) -> VisitItem:
    return VisitItem(
        item_id=f"lunch-{day}",
        name="午饭（自由安排）",
        category="food",
        city="西安",
        day=day,
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        pinned=True,
    )


# ---------- 1) 场次解析 ----------


def test_show_session_starts_parses_session_lists():
    assert show_session_starts("多场（约15:00/20:00，旺季加场至4场）") == [
        15 * 60,
        20 * 60,
    ]
    assert show_session_starts("傍晚/晚间场（约17:30/19:30两场）") == [
        17 * 60 + 30,
        19 * 60 + 30,
    ]
    assert show_session_starts(
        "多场（白天约11:10/12:00/13:40/16:20/17:10，平日约3场）"
    ) == [
        11 * 60 + 10,
        12 * 60,
        13 * 60 + 40,
        16 * 60 + 20,
        17 * 60 + 10,
    ]
    assert show_session_starts("09:00-17:00") == []
    assert show_session_starts("") == []


def test_show_session_starts_empty_for_none():
    assert show_session_starts(None) == []


# ---------- 2) solver：场次开窗 ----------


def test_solve_day_two_shows_land_on_real_sessions():
    a = _visit(
        "sa",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="多场（约13:40/16:20）",
    )
    b = _visit(
        "sb",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="多场（约14:00/16:30）",
    )
    day = DayPlan(day=1, base_city="西安", items=[a, b, _lunch()])

    solved = solve_day(day, poi_hours=[])

    assert solved is not None
    starts = {}
    for i in solved.items:
        if isinstance(i, VisitItem) and i.item_id in ("sa", "sb"):
            starts[i.item_id] = i.start_time.hour * 60 + i.start_time.minute
    assert starts["sa"] in (13 * 60 + 40, 16 * 60 + 20)
    assert starts["sb"] in (14 * 60, 16 * 60 + 30)


def test_solve_day_three_shows_same_day_still_infeasible():
    """事故原形：三场演出+午餐钉 12 点在真场次下仍不可行（场次彼此
    错不开）——按日降级+上午保底负责收口，不再拖垮其他天。"""
    f = _visit(
        "sf",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="多场（白天约11:10/12:00/13:40/16:20/17:10，平日约3场）",
    )
    q = _visit(
        "sq",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="多场（约14:00/16:30，旺季11:00起加场）",
    )
    r = _visit(
        "sr",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="多场（约11:00/14:00/17:00，以当日公告为准）",
    )
    day = DayPlan(day=1, base_city="西安", items=[f, q, r, _lunch()])

    assert solve_day(day, poi_hours=[]) is None


def test_solve_day_evening_only_show_flight_day_infeasible():
    s = _visit(
        "se",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="傍晚/晚间场（约17:30/19:30两场）",
    )
    flight = TransferItem(
        day=1,
        seq=1,
        mode="flight",
        item_id="t1",
        from_city="西安",
        to_city="上海",
        start_time=time(17, 0),
        end_time=time(20, 0),
        duration_minutes=180,
    )
    day = DayPlan(day=1, base_city="西安", items=[s, flight, _lunch()])

    assert solve_day(day, poi_hours=[]) is None


# ---------- 3) 兜底排列三修正 ----------


def test_fallback_places_180min_sight_before_lunch():
    v = _visit("big", dur=180)
    day = DayPlan(day=1, base_city="西安", items=[v, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    _fallback_sequence_times(plan)

    assert v.start_time == time(9, 0) and v.end_time == time(12, 0)


def test_fallback_failure_does_not_poison_cursor():
    """180 分钟被钉点+航班夹死排不上；后面的 80 分钟点仍要落位。"""
    pinned = VisitItem(
        item_id="fix",
        name="fix",
        city="西安",
        day=1,
        start_time=time(10, 0),
        end_time=time(11, 0),
        duration_minutes=60,
        pinned=True,
    )
    # 2026-10-31 午餐可顺延（用户拍板）后 180 分钟已能穿过 12 点午餐锚
    # 落位——本例改 300 分钟保持「真排不下」语义：航班缓冲夹死、
    # small 仍要回填（游标不被前面失败顶飞）。
    big = _visit("big", dur=300)
    small = _visit("small", dur=80)
    flight = TransferItem(
        day=1,
        seq=1,
        mode="flight",
        item_id="t1",
        from_city="西安",
        to_city="上海",
        start_time=time(17, 0),
        end_time=time(20, 0),
        duration_minutes=180,
    )
    day = DayPlan(day=1, base_city="西安", items=[pinned, big, small, flight, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    _fallback_sequence_times(plan)

    assert big.start_time is None  # 真排不下
    assert small.start_time is not None  # 不被前面失败顶飞


def test_fallback_evening_show_never_morning():
    s = _visit("show", dur=80, best_visit_time="show", category="entertainment")
    day = DayPlan(day=1, base_city="西安", items=[s, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    _fallback_sequence_times(plan)

    assert s.start_time is not None
    assert s.start_time.hour >= 17


def test_fallback_session_show_lands_on_session():
    s = _visit(
        "s",
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="多场（约15:00/20:00）",
    )
    day = DayPlan(day=1, base_city="西安", items=[s, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    _fallback_sequence_times(plan)

    assert s.start_time in (time(15, 0), time(20, 0))


# ---------- 4) 上午保底 ----------


def _afternoon_only_plan():
    show = VisitItem(
        item_id="v9",
        name="下午秀",
        category="entertainment",
        city="西安",
        day=1,
        best_visit_time="show",
        start_time=time(14, 0),
        end_time=time(15, 20),
        duration_minutes=80,
        pinned=True,
    )
    day = DayPlan(day=1, base_city="西安", items=[show, _lunch()])
    return ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day]), day


def test_morning_occupied_detection():
    _, day = _afternoon_only_plan()
    assert not _morning_occupied(day)
    day.items.append(
        VisitItem(
            item_id="vm",
            name="晨点",
            city="西安",
            day=1,
            start_time=time(9, 0),
            end_time=time(10, 0),
            duration_minutes=60,
        )
    )
    assert _morning_occupied(day)


def test_morning_fill_adds_indoor_museum():
    agent = PlanningAgent(_NoLLM())
    plan, day = _afternoon_only_plan()
    cands = [
        {
            "name": "陕西历史博物馆",
            "city": "西安",
            "category": "museum",
            "source_poi_id": "4a_slb",
            "suggested_duration_min": 120,
            "rain_ok": "yes",
            "best_visit_time": "any",
        }
    ]

    added = agent._morning_fill(plan, day, [{"name": "下午秀", "day": 1}], cands)

    assert added == "陕西历史博物馆"
    visit = next(i for i in day.items if i.name == "陕西历史博物馆")
    assert visit.start_time == time(9, 0)


def test_morning_fill_rainy_day_rejects_outdoor():
    agent = PlanningAgent(_NoLLM())
    plan, day = _afternoon_only_plan()
    cands = [
        {
            "name": "露天公园",
            "city": "西安",
            "category": "attraction",
            "source_poi_id": "ct_x1",
            "suggested_duration_min": 90,
            "rain_ok": "no",
            "best_visit_time": "any",
        }
    ]

    added = agent._morning_fill(
        plan,
        day,
        [{"name": "下午秀", "day": 1}],
        cands,
        rain_days={"西安": {1}},
    )

    assert added is None
    assert all(i.name != "露天公园" for i in day.items)


def test_morning_fill_skips_already_picked_and_wrong_city():
    agent = PlanningAgent(_NoLLM())
    plan, day = _afternoon_only_plan()
    cands = [
        {
            "name": "下午秀",
            "city": "西安",
            "category": "attraction",
            "suggested_duration_min": 90,
            "rain_ok": "yes",
        },
        {
            "name": "外地点",
            "city": "北京",
            "category": "attraction",
            "suggested_duration_min": 90,
            "rain_ok": "yes",
        },
        {
            "name": "碑林博物馆",
            "city": "西安",
            "category": "museum",
            "source_poi_id": "ct_bl",
            "suggested_duration_min": 90,
            "rain_ok": "yes",
            "best_visit_time": "any",
        },
    ]

    added = agent._morning_fill(plan, day, [{"name": "下午秀", "day": 1}], cands)

    assert added == "碑林博物馆"
