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
        start_time=time(9, 0),
        end_time=time(10, 0),
        duration_minutes=60,
        pinned=True,
    )
    # 2026-10-31 午餐可顺延（用户拍板）后 180 分钟已能穿过 12 点午餐锚
    # 落位——本例改 300 分钟保持「真排不下」语义：航班缓冲夹死、
    # small 仍要回填（游标不被前面失败顶飞）。钉点挪 9:00-10:00：
    # 17:00 航班触发离城日上午闸（end ≤ 12:00），10:00 起钉会把
    # small 的 80 分钟顶过闸（2026-11-03 拍板口径下保持测试意图）。
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


def test_fallback_sessionless_show_schedules_normally():
    """无场次演出按正常景点排（2026-11-06 拍板，废除 17:00 晚场地板）：
    无营业窗、无场次串 → 随游标正常落位，不再钉晚场。"""
    s = _visit("show", dur=80, best_visit_time="show", category="entertainment")
    day = DayPlan(day=1, base_city="西安", items=[s, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    _fallback_sequence_times(plan)

    assert s.start_time is not None
    assert s.start_time == time(9, 0)
    assert s.end_time == time(10, 20)


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


# ---------- 5) 午餐软钉（solver 侧，2026-10-31 拍板「午餐可以延后」） ----------


def _soft_lunch(day=1, *, soft=True):
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
        soft_pin=soft,
    )


def _big(day=1, dur=240):
    return _visit("big", dur=dur, day=day)


def test_meal_flex_rule_240min_big_lands_after_shortened_lunch():
    """2026-11-01 规则修正（±30 分钟 + 时长可缩 30）：240 分钟大点塞不进
    上午窗（≤12:30=210 分钟容量）——贴着缩短的午餐后落位；午餐开餐
    ±30 内、时长 ≥30；全程无重叠。"""
    day = DayPlan(day=1, base_city="西安", items=[_soft_lunch(), _big(dur=240)])
    solved = solve_day(day, poi_hours=[], meal_flex=True)
    assert solved is not None
    starts = {i.item_id: i.start_time for i in solved.items}
    ends = {i.item_id: i.end_time for i in solved.items}
    # 午餐在 ±30 窗内开餐
    assert time(11, 30) <= starts["lunch-1"] <= time(12, 30)
    # 大点贴着午餐可行域后落位（makespan 最优=缩短午餐 11:30-12:00 + 12:00 起）
    assert starts["big"] == time(12, 0)
    assert ends["big"] == time(16, 0)
    # 无重叠
    assert ends["lunch-1"] <= starts["big"] or ends["big"] <= starts["lunch-1"]


def test_meal_flex_180min_big_keeps_morning_zero_drift():
    """180 分钟大点 09:00-12:00 与 12:00 午餐零漂移紧贴（±30 许可不需要
    动用——makespan 最优即零漂移）。"""
    day = DayPlan(day=1, base_city="西安", items=[_soft_lunch(), _big(dur=180)])
    solved = solve_day(day, poi_hours=[], meal_flex=True)
    assert solved is not None
    starts = {i.item_id: i.start_time for i in solved.items}
    assert starts["big"] == time(9, 0)
    assert starts["lunch-1"] == time(12, 0)


def test_user_pinned_lunch_stays_hard_under_meal_flex():
    """用户手钉（soft_pin=False）的午餐：meal_flex 也不动（铁律 19）。"""
    day = DayPlan(
        day=1, base_city="西安", items=[_soft_lunch(soft=False), _big(dur=180)]
    )
    solved = solve_day(day, poi_hours=[], meal_flex=True)
    assert solved is not None
    starts = {i.item_id: i.start_time for i in solved.items}
    assert starts["lunch-1"] == time(12, 0)  # 纹丝不动
    # NoOverlap 允许紧贴：大点 09:00-12:00 恰好接午餐 12:00（合法且更优）
    assert starts["big"] == time(9, 0)


def test_meal_flex_off_keeps_system_lunch():
    """编辑/重排路径 meal_flex=False：系统钉午餐也不漂移。"""
    day = DayPlan(day=1, base_city="西安", items=[_soft_lunch(), _big(dur=180)])
    solved = solve_day(day, poi_hours=[], meal_flex=False)
    assert solved is not None
    starts = {i.item_id: i.start_time for i in solved.items}
    assert starts["lunch-1"] == time(12, 0)


def test_solve_plan_forwards_meal_flex():
    from app.services.itinerary.solver import solve_plan

    day = DayPlan(day=1, base_city="西安", items=[_soft_lunch(), _big(dur=180)])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])
    solved = solve_plan(plan, poi_hours=[], meal_flex=True)
    assert solved is not None
    starts = {i.item_id: i.start_time for i in solved.days[0].items}
    assert starts["big"] == time(9, 0)


def test_fallback_delays_system_lunch_but_not_user_pinned():
    """兜底口径对齐：soft_pin 午餐按 2026-11-03 开餐硬窗 [11:30, 12:30]
    裁决——240 分钟大点 09:00-13:00 整段压窗 → 当天移除（不再无界顺延）；
    用户手钉午餐不动，大点让到下午。"""
    from app.services.agent.plan import _fallback_sequence_times

    soft_day = DayPlan(day=1, base_city="西安", items=[_soft_lunch(), _big(dur=240)])
    soft_plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[soft_day])
    _fallback_sequence_times(soft_plan)
    s = {i.item_id: i.start_time for i in soft_day.items}
    assert s["big"] == time(9, 0)
    # 硬窗被大点整段压满：移除（铁律 20 同义，不产 8pm 午餐）
    assert "lunch-1" not in s

    hard_day = DayPlan(
        day=1, base_city="西安", items=[_soft_lunch(soft=False), _big(dur=240)]
    )
    hard_plan = ItineraryPlan(itinerary_id="it2", cities=["西安"], days=[hard_day])
    _fallback_sequence_times(hard_plan)
    h = {i.item_id: i.start_time for i in hard_day.items}
    assert h["lunch-1"] == time(12, 0)  # 用户钉不动
    # 2026-11-07 开场闸 16:00（大点 15:30 带）：240 分钟大点 13:00 起
    # ≤ 15:30 → 让到下午 13:00-17:00 合法（11-05 结束闸口径已废）
    assert h["big"] == time(13, 0)


# ---------- 6) 预算=偏好 + 跨天借调（2026-11-01 拍板） ----------


def _borrow_fixture():
    """用户 4f228cfb 案形状：day3 雨天空上午（软午餐+华清池 240+未排
    秦俑情），day4 兵马俑 09:00 + 钟楼 11:00。"""
    from app.services.itinerary.models import GeoPoint

    lunch = VisitItem(
        item_id="lunch-3",
        name="午饭（自由安排）",
        category="food",
        city="西安",
        day=3,
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        pinned=True,
        soft_pin=True,
    )
    hqc = VisitItem(
        item_id="v-hqc",
        name="临潼区华清池景区",
        category="attraction",
        city="西安",
        day=3,
        rain_ok="no",
        start_time=time(13, 0),
        end_time=time(17, 0),
        duration_minutes=240,
        location=GeoPoint(lon=109.21, lat=34.36),
    )
    show = VisitItem(
        item_id="v-qyq",
        name="《秦俑情》",
        category="entertainment",
        city="西安",
        day=3,
        rain_ok="yes",
        best_visit_time="show",
        opening_hours="多场（约11:00/14:00/17:00）",
        duration_minutes=80,
        location=GeoPoint(lon=109.28, lat=34.38),
    )
    bmy = VisitItem(
        item_id="v-bmy",
        name="秦始皇兵马俑博物馆",
        category="attraction",
        city="西安",
        day=4,
        rain_ok="yes",
        best_visit_time="any",
        start_time=time(9, 0),
        end_time=time(10, 30),
        duration_minutes=90,
        location=GeoPoint(lon=109.27, lat=34.38),
    )
    zl = VisitItem(
        item_id="v-zl",
        name="钟楼",
        category="sight",
        city="西安",
        day=4,
        rain_ok="yes",
        best_visit_time="any",
        start_time=time(11, 0),
        end_time=time(12, 0),
        duration_minutes=60,
        location=GeoPoint(lon=108.94, lat=34.26),
    )
    day3 = DayPlan(day=3, base_city="西安", items=[lunch, hqc, show])
    day4 = DayPlan(day=4, base_city="西安", items=[bmy, zl])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day3, day4])
    return plan, day3, day4


def _picked4():
    return [
        {"name": "临潼区华清池景区"},
        {"name": "《秦俑情》"},
        {"name": "秦始皇兵马俑博物馆"},
        {"name": "钟楼"},
    ]


def _slb_cand():
    return {
        "name": "陕西历史博物馆",
        "city": "西安",
        "category": "museum",
        "source_poi_id": "4a_slb",
        "suggested_duration_min": 120,
        "rain_ok": "yes",
        "best_visit_time": "any",
        "location": {"lon": 108.95, "lat": 34.24},
    }


def test_morning_borrow_moves_bmy_to_blank_rainy_morning():
    agent = PlanningAgent(_NoLLM())
    plan, day3, day4 = _borrow_fixture()

    res = agent._morning_borrow(
        plan,
        day3,
        _picked4(),
        [_slb_cand()],
        rain_days={"西安": {3, 4}},
    )

    assert res == ("秦始皇兵马俑博物馆", "陕西历史博物馆", 4)
    bmy = next(i for i in day3.items if i.name == "秦始皇兵马俑博物馆")
    assert bmy.day == 3
    assert bmy.start_time == time(9, 0)
    assert _morning_occupied(day4)  # 钟楼 11:00 仍在
    slb = next(i for i in day4.items if i.name == "陕西历史博物馆")
    assert slb.start_time is not None


def test_morning_borrow_geo_prefers_lintong_cluster():
    """day2(市区)与 day4(临潼)都可借时，地理亲和度选临潼簇的兵马俑。"""
    from app.services.itinerary.models import GeoPoint

    agent = PlanningAgent(_NoLLM())
    plan, day3, day4 = _borrow_fixture()
    hj = VisitItem(
        item_id="v-hj",
        name="回民街",
        category="attraction",
        city="西安",
        day=2,
        rain_ok="yes",
        best_visit_time="any",
        start_time=time(9, 0),
        end_time=time(10, 30),
        duration_minutes=90,
        location=GeoPoint(lon=108.93, lat=34.26),
    )
    day2 = DayPlan(day=2, base_city="西安", items=[hj])
    plan.days.insert(0, day2)

    res = agent._morning_borrow(
        plan,
        day3,
        _picked4() + [{"name": "回民街"}],
        [_slb_cand()],
        rain_days={"西安": {3, 4}},
    )

    assert res is not None
    assert res[0] == "秦始皇兵马俑博物馆"
    assert res[2] == 4


def test_morning_borrow_reverts_when_donor_morning_would_blank():
    agent = PlanningAgent(_NoLLM())
    plan, day3, day4 = _borrow_fixture()
    day4.items = [i for i in day4.items if i.name != "钟楼"]  # 兵马俑是唯一晨点

    res = agent._morning_borrow(plan, day3, _picked4(), [], rain_days={"西安": {3, 4}})

    assert res is None
    assert not any(i.name == "秦始皇兵马俑博物馆" for i in day3.items)
    bmy = next(i for i in day4.items if i.name == "秦始皇兵马俑博物馆")
    assert bmy.day == 4


def test_morning_borrow_skips_pinned_and_show():
    agent = PlanningAgent(_NoLLM())
    plan, day3, day4 = _borrow_fixture()
    for i in day4.items:
        i.pinned = True  # 钟楼+兵马俑全钉 → 不可借

    res = agent._morning_borrow(plan, day3, _picked4(), [], rain_days={"西安": {3, 4}})

    assert res is None


def test_morning_borrow_tries_next_donor_when_best_blanks_donor():
    """最佳候选会掏空白借出日上午时，按亲和序还原后试下一个候选，
    不再一次性放弃（2026-11-02 用户案：day3 空上午+day4 双晨点）。"""
    from app.services.itinerary.models import GeoPoint

    agent = PlanningAgent(_NoLLM())
    plan, day3, day4 = _borrow_fixture()
    zl = next(i for i in day4.items if i.name == "钟楼")
    zl.start_time = time(13, 0)  # 兵马俑成 day4 唯一晨点 → 借出即空白
    zl.end_time = time(14, 0)
    zl.best_visit_time = "afternoon"  # 且不具借出资格 → 下一候选才是回民街
    hj = VisitItem(
        item_id="v-hj",
        name="回民街",
        category="attraction",
        city="西安",
        day=2,
        rain_ok="yes",
        best_visit_time="any",
        start_time=time(9, 0),
        end_time=time(10, 30),
        duration_minutes=90,
        location=GeoPoint(lon=108.93, lat=34.26),
    )
    bl = VisitItem(
        item_id="v-bl",
        name="西安碑林博物馆",
        category="museum",
        city="西安",
        day=2,
        rain_ok="yes",
        best_visit_time="any",
        start_time=time(11, 0),
        end_time=time(12, 0),
        duration_minutes=60,
        location=GeoPoint(lon=108.93, lat=34.25),
    )
    day2 = DayPlan(day=2, base_city="西安", items=[hj, bl])
    plan.days.insert(0, day2)

    res = agent._morning_borrow(
        plan, day3, _picked4() + [{"name": "回民街"}, {"name": "西安碑林博物馆"}], []
    )

    assert res == ("回民街", None, 2)
    hj2 = next(i for i in day3.items if i.name == "回民街")
    assert hj2.day == 3
    assert hj2.start_time == time(9, 0)
    bmy = next(i for i in day4.items if i.name == "秦始皇兵马俑博物馆")
    assert bmy.day == 4  # 最佳候选整体还原，不残留半挪状态
    assert _morning_occupied(day2)  # 碑林 11:00 仍在
    assert _morning_occupied(day4)  # 兵马俑还原后晨点仍在


def test_morning_borrow_can_move_must_wish_item():
    """心愿/必去点时间可挪不可删（2026-11-02 拍板：钉的是在册，
    不是时刻）——上午借调可把必去点挪进空上午，只要它不消失、
    借出日上午不空白。"""
    agent = PlanningAgent(_NoLLM())
    plan, day3, day4 = _borrow_fixture()

    res = agent._morning_borrow(
        plan,
        day3,
        [
            {"name": "临潼区华清池景区"},
            {"name": "《秦俑情》"},
            {"name": "秦始皇兵马俑博物馆", "must": True},
            {"name": "钟楼"},
        ],
        [_slb_cand()],
        rain_days={"西安": {3, 4}},
    )

    assert res is not None
    assert res[0] == "秦始皇兵马俑博物馆"  # 必去点=最佳亲和候选，被借入 day3
    bmy = next(i for i in day3.items if i.name == "秦始皇兵马俑博物馆")
    assert bmy.day == 3
    assert bmy.start_time == time(9, 0)
    assert _morning_occupied(day4)  # 钟楼 11:00 仍在，必去点未消失


def test_morning_fill_overflow_adds_shortest_when_budget_soft():
    """360=偏好非硬闸：全都装不下时按最短溢出补，不再拒绝。"""
    agent = PlanningAgent(_NoLLM())
    plan, day = _afternoon_only_plan()
    day.items.append(
        VisitItem(
            item_id="v-big1",
            name="大点甲",
            category="attraction",
            city="西安",
            day=1,
            start_time=time(16, 0),
            end_time=time(20, 0),
            duration_minutes=240,
        )
    )
    cands = [
        {
            "name": "长点乙",
            "city": "西安",
            "category": "museum",
            "source_poi_id": "ct_b",
            "suggested_duration_min": 180,
            "rain_ok": "yes",
            "best_visit_time": "any",
        },
        {
            "name": "短点丙",
            "city": "西安",
            "category": "museum",
            "source_poi_id": "ct_c",
            "suggested_duration_min": 90,
            "rain_ok": "yes",
            "best_visit_time": "any",
        },
    ]

    # 不许溢出（第一阶段）：全都装不下 → None
    assert agent._morning_fill(plan, day, [], cands, allow_overflow=False) is None
    # 允许溢出（第三阶段）：按最短溢出补「短点丙」
    added = agent._morning_fill(plan, day, [], cands, allow_overflow=True)
    assert added == "短点丙"
    visit = next(i for i in day.items if i.name == "短点丙")
    assert visit.start_time == time(9, 0)


def test_morning_fill_never_refills_same_heritage_site():
    """2026-11-01 秦陵双卡案：D2 已排「秦始皇陵国家考古遗址公园」，D1
    空窗上午保底不得把同馆的「秦始皇兵马俑博物馆」补进来（守卫走全量
    同站判定而非包含判定），顺延到下一个非重样候选。"""
    agent = PlanningAgent(_NoLLM())
    plan, day = _afternoon_only_plan()
    plan.days.append(
        DayPlan(
            day=2,
            base_city="西安",
            items=[
                VisitItem(
                    item_id="vq",
                    name="秦始皇陵国家考古遗址公园",
                    category="attraction",
                    city="西安",
                    day=2,
                    start_time=time(15, 0),
                    end_time=time(16, 30),
                    duration_minutes=90,
                )
            ],
        )
    )
    cands = [
        {
            "name": "秦始皇兵马俑博物馆",
            "city": "西安",
            "category": "attraction",
            "source_poi_id": "5a_296",
            "suggested_duration_min": 90,
            "rain_ok": "yes",
            "best_visit_time": "any",
        },
        {
            "name": "陕西历史博物馆",
            "city": "西安",
            "category": "museum",
            "source_poi_id": "4a_slb",
            "suggested_duration_min": 120,
            "rain_ok": "yes",
            "best_visit_time": "any",
        },
    ]

    added = agent._morning_fill(plan, day, [{"name": "下午秀", "day": 1}], cands)

    assert added == "陕西历史博物馆"
    assert all(i.name != "秦始皇兵马俑博物馆" for i in day.items)
