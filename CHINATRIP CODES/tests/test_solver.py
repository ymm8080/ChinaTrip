"""Offline deterministic tests for the CP-SAT itinerary solver (§6.9)."""

from datetime import time

from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    PoiHours,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import solve_day, solve_plan

_ALL_DAY = PoiHours(poi_id="p_all", opens=time(8, 0), closes=time(21, 0))


def _visit(
    item_id: str, *, poi_id: str | None = None, dur=60, city="北京", **kwargs
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        poi_id=poi_id,
        city=city,
        day=1,
        duration_minutes=dur,
        **kwargs,
    )


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def test_unordered_visits_get_ordered_inside_windows():
    items = [
        _visit("v_late", poi_id="p_all", dur=90),
        _visit("v_morning", poi_id="p_morning", dur=60),
        _visit("v_mid", poi_id="p_all", dur=None),  # falls back to 60 minutes
    ]
    day = DayPlan(day=1, base_city="北京", items=items)
    hours = [
        PoiHours(poi_id="p_morning", opens=time(9, 0), closes=time(12, 0)),
        _ALL_DAY,
    ]

    solved = solve_day(day, poi_hours=hours)

    assert solved is not None
    assert {i.item_id for i in solved.items} == {"v_late", "v_morning", "v_mid"}
    starts = [_minutes(i.start_time) for i in solved.items]
    assert starts == sorted(starts)  # output is ordered
    for prev, nxt in zip(solved.items, solved.items[1:]):
        assert prev.end_time <= nxt.start_time  # no overlap
    expected_dur = {"v_late": 90, "v_morning": 60, "v_mid": 60}
    for item in solved.items:
        assert (
            _minutes(item.end_time) - _minutes(item.start_time)
            == expected_dur[item.item_id]
        )
        assert 8 * 60 <= _minutes(item.start_time)
        assert _minutes(item.end_time) <= 21 * 60
    morning = next(i for i in solved.items if i.item_id == "v_morning")
    assert _minutes(morning.start_time) >= 9 * 60
    assert _minutes(morning.end_time) <= 12 * 60
    # the input day is not mutated
    assert all(i.start_time is None and i.end_time is None for i in day.items)


def test_pinned_visit_keeps_its_time():
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _visit("v_free", poi_id="p_all"),
            _visit(
                "v_pin", poi_id="p_all", dur=90, pinned=True, start_time=time(10, 0)
            ),
        ],
    )

    solved = solve_day(day, poi_hours=[_ALL_DAY])

    assert solved is not None
    pin = next(i for i in solved.items if i.item_id == "v_pin")
    assert (pin.start_time, pin.end_time) == (time(10, 0), time(11, 30))
    free = next(i for i in solved.items if i.item_id == "v_free")
    assert free.end_time <= time(10, 0) or free.start_time >= time(11, 30)


def test_pinned_outside_window_is_infeasible():
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[_visit("v_pin", poi_id="p_short", pinned=True, start_time=time(10, 0))],
    )
    hours = [PoiHours(poi_id="p_short", opens=time(9, 0), closes=time(9, 30))]

    assert solve_day(day, poi_hours=hours) is None


def test_travel_matrix_orders_visits():
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _visit("c", poi_id="pc"),
            _visit("a", poi_id="pa"),
            _visit("b", poi_id="pb"),
        ],
    )
    matrix = {
        ("pa", "pb"): 10,
        ("pb", "pc"): 10,
        ("pa", "pc"): 60,
    }  # every other ordered pair misses the matrix -> default 30
    # optimal tour a->b->c costs 20; any other order costs >= 40.

    solved = solve_day(day, poi_hours=[_ALL_DAY], travel_minutes=matrix)

    assert solved is not None
    assert [i.item_id for i in solved.items] == ["a", "b", "c"]


def test_window_too_short_is_infeasible():
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[_visit("v_long", poi_id="p_short", dur=300)],  # 5 hours
    )
    hours = [PoiHours(poi_id="p_short", opens=time(9, 0), closes=time(12, 0))]  # 3h

    assert solve_day(day, poi_hours=hours) is None


def test_visits_avoid_transfer_buffer():
    transfer = TransferItem(
        item_id="t1",
        day=1,
        seq=1,
        from_city="北京",
        to_city="上海",
        start_time=time(13, 0),
        end_time=time(15, 0),
    )
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[transfer, _visit("v", poi_id="p_all")],
    )

    solved = solve_day(day, poi_hours=[_ALL_DAY])

    assert solved is not None
    visit = next(i for i in solved.items if i.item_id == "v")
    # buffer: end <= 11:30 or start >= 16:30 (13:00/15:00 +/- 90 minutes)
    assert visit.end_time <= time(11, 30) or visit.start_time >= time(16, 30)
    out_transfer = next(i for i in solved.items if i.item_id == "t1")
    assert (out_transfer.start_time, out_transfer.end_time) == (
        time(13, 0),
        time(15, 0),
    )


def test_transfer_missing_end_time_is_filled():
    transfer = TransferItem(
        item_id="t1",
        day=1,
        seq=1,
        from_city="北京",
        to_city="上海",
        start_time=time(9, 0),
        duration_minutes=120,
    )
    day = DayPlan(
        day=1,
        base_city="北京",
        # 城市侧闸（2026-11-02）：转场日 16:00 的条目须是到达城（上海）；
        # 出发城条目不得排在离城交通之后。30 分钟点 16:00-16:30 收尾
        # 在 11-05 结束闸内（60 分钟点 16:00-17:00 已是被废除的形态）。
        items=[transfer, _visit("v", poi_id="p_afternoon", city="上海", dur=30)],
    )
    hours = [PoiHours(poi_id="p_afternoon", opens=time(16, 0), closes=time(18, 0))]

    solved = solve_day(day, poi_hours=hours)

    assert solved is not None
    out_transfer = next(i for i in solved.items if i.item_id == "t1")
    assert out_transfer.end_time == time(11, 0)
    visit = next(i for i in solved.items if i.item_id == "v")
    assert (visit.start_time, visit.end_time) == (time(16, 0), time(16, 30))


def test_same_city_transfer_leg_does_not_gate():
    """退化转场腿（规整后 from==to，环线大巴/脏数据）整腿不判：先匹配
    to_city 会把同城条目全判 "after"，上午条目团灭、整天 None
    （2026-11-02 审计，宁不加码不可错拦）。"""
    transfer = TransferItem(
        item_id="t1",
        day=1,
        seq=1,
        from_city="上海",
        to_city="上海市",  # 规整后与 from 同城 → 退化腿
        start_time=time(13, 0),
        end_time=time(15, 0),
    )
    day = DayPlan(
        day=1,
        base_city="上海",
        items=[transfer, _visit("v", poi_id="p_morning", city="上海")],
    )
    hours = [PoiHours(poi_id="p_morning", opens=time(9, 0), closes=time(12, 0))]

    solved = solve_day(day, poi_hours=hours)

    assert solved is not None
    visit = next(i for i in solved.items if i.item_id == "v")
    assert visit.end_time <= time(12, 0)  # 上午照排，不被判 "after"


def test_empty_day_round_trips():
    day = DayPlan(day=3, base_city="西安", items=[])

    solved = solve_day(day, poi_hours=[])

    assert solved is not None
    assert solved.day == 3
    assert solved.base_city == "西安"
    assert solved.items == []


def test_solve_plan_degrades_per_day():
    """2026-10-31 上午空排事故：旧「单日失败作废整单」把其余天的好解
    一起拖进顺序兜底（第2/3天上午全空）；现在失败日原样保留（untimed
    交给调用方兜底），好天保住 solver 优化解。"""
    ok_day = DayPlan(day=1, base_city="北京", items=[_visit("v1", poi_id="p_short")])
    bad_day = DayPlan(
        day=2, base_city="上海", items=[_visit("v2", poi_id="p_short", dur=300)]
    )
    hours = [PoiHours(poi_id="p_short", opens=time(9, 0), closes=time(12, 0))]
    plan = ItineraryPlan(
        itinerary_id="it1", cities=["北京", "上海"], days=[ok_day, bad_day]
    )

    solved = solve_plan(plan, poi_hours=hours)

    assert solved is not None
    day1, day2 = solved.days
    assert day1.items[0].start_time is not None  # 好天保住解
    assert all(i.start_time is None for i in day2.items)  # 坏天原样保留


def test_solve_plan_solves_all_days():
    plan = ItineraryPlan(
        itinerary_id="it1",
        cities=["北京", "上海"],
        days=[
            DayPlan(day=1, base_city="北京", items=[_visit("v1", poi_id="p_all")]),
            DayPlan(day=2, base_city="上海", items=[_visit("v2", poi_id="p_all")]),
        ],
    )

    solved = solve_plan(plan, poi_hours=[_ALL_DAY])

    assert solved is not None
    assert solved.itinerary_id == "it1"
    assert solved.cities == ["北京", "上海"]
    assert [d.day for d in solved.days] == [1, 2]
    for day in solved.days:
        assert len(day.items) == 1
        assert day.items[0].start_time is not None
        assert day.items[0].end_time is not None


# --- 8.2.1 best_visit_time 时段窗 ---


def test_best_visit_evening_starts_after_17():
    # 夜景类 POI 自动排进傍晚窗 17:00-21:00
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[_visit("v_night", poi_id="p_all", best_visit_time="evening")],
    )

    solved = solve_day(day, poi_hours=[_ALL_DAY])

    assert solved is not None
    visit = next(i for i in solved.items if i.item_id == "v_night")
    assert _minutes(visit.start_time) >= 17 * 60
    assert _minutes(visit.end_time) <= 21 * 60


def test_best_visit_morning_intersects_poi_hours():
    # 时段窗 08:00-12:00 与营业窗 09:00-11:00 相交 → 只能落交集内
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[_visit("v_m", poi_id="p_hours", best_visit_time="morning")],
    )
    hours = [PoiHours(poi_id="p_hours", opens=time(9, 0), closes=time(11, 0))]

    solved = solve_day(day, poi_hours=hours)

    assert solved is not None
    visit = next(i for i in solved.items if i.item_id == "v_m")
    assert _minutes(visit.start_time) >= 9 * 60
    assert _minutes(visit.end_time) <= 11 * 60


def test_best_visit_sunrise_pinned_08_still_legal():
    # sunrise 窗 08:00-10:30 覆盖 08:00 锚点，pinned 条目保持铁律 19 不动
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _visit(
                "v_sunrise",
                poi_id="p_all",
                best_visit_time="sunrise",
                pinned=True,
                start_time=time(8, 0),
            )
        ],
    )

    solved = solve_day(day, poi_hours=[_ALL_DAY])

    assert solved is not None
    pin = next(i for i in solved.items if i.item_id == "v_sunrise")
    assert pin.start_time == time(8, 0)


def test_best_visit_unknown_value_does_not_constrain():
    # 未知枚举（库脏数据）按 "any" 处理：5h 时长不收窄仍可解；
    # 若误按 morning 08:00-12:00 收窄则必为 None
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[_visit("v_weird", poi_id="p_all", best_visit_time="weird", dur=300)],
    )

    solved = solve_day(day, poi_hours=[_ALL_DAY])

    assert solved is not None
    visit = next(i for i in solved.items if i.item_id == "v_weird")
    assert _minutes(visit.start_time) >= 8 * 60
    assert _minutes(visit.end_time) <= 21 * 60


def test_best_visit_evening_too_long_is_infeasible():
    # evening 窗仅 240 分钟，塞不下 5h 时长 → 整日不可行（原子性不变）
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[_visit("v_evening", poi_id="p_all", best_visit_time="evening", dur=300)],
    )

    assert solve_day(day, poi_hours=[_ALL_DAY]) is None


# --- G3：多窗营业时间（午休闭馆） -------------------------------------------


def _day_with_windows(windows):
    from datetime import time as t

    from app.services.itinerary.models import DayPlan, PoiHours, VisitItem

    visit = VisitItem(
        item_id="v1",
        name="午休馆",
        poi_id="P1",
        city="上海",
        day=1,
        duration_minutes=60,
    )
    hours = PoiHours(
        poi_id="P1",
        opens=t(9, 0),
        closes=t(17, 0),
        windows=[(t(a, b), t(c, d)) for a, b, c, d in windows],
    )
    day = DayPlan(day=1, base_city="上海", items=[visit])
    return day, [hours]


def test_multi_window_visit_avoids_lunch_break():
    from app.services.itinerary.solver import solve_day

    day, hours = _day_with_windows([(9, 0, 12, 0), (13, 30, 17, 0)])
    solved = solve_day(day, poi_hours=hours)
    assert solved is not None
    visit = solved.items[0]
    start = visit.start_time.hour * 60 + visit.start_time.minute
    end = start + 60
    in_first = 9 * 60 <= start and end <= 12 * 60
    in_second = 13 * 60 + 30 <= start and end <= 17 * 60
    assert in_first or in_second  # 不许骑在午休段上


def test_multi_window_infeasible_when_dur_exceeds_every_segment():
    from app.services.itinerary.solver import solve_day

    day, hours = _day_with_windows([(9, 0, 10, 0), (13, 0, 14, 0)])
    day.items[0].duration_minutes = 120  # 任一段都塞不下
    assert solve_day(day, poi_hours=hours) is None


def test_plan_poi_hours_parses_lunch_break_complement():
    from app.services.agent.plan import _plan_poi_hours
    from app.services.itinerary.models import DayPlan, VisitItem

    visit = VisitItem(
        item_id="v1",
        name="馆",
        poi_id="P1",
        city="上海",
        day=1,
        opening_hours="开放时间：09:00-17:00（12:00-13:30 午休闭馆）",
    )
    plan = type("P", (), {"days": [DayPlan(day=1, base_city="上海", items=[visit])]})()
    hours = _plan_poi_hours(plan)
    assert len(hours) == 1 and hours[0].windows
    ws = [(o.hour * 60 + o.minute, c.hour * 60 + c.minute) for o, c in hours[0].windows]
    assert ws == [(9 * 60, 12 * 60), (13 * 60 + 30, 17 * 60)]


# --- 无场次演出两档分流（2026-11-11 拍板，取代 2026-11-06「按正常景点排」）---


def test_show_without_sessions_schedules_like_normal_sight():
    """无场次 SHOW 落位域自中午起开：不钉 20:10 晚场，也不回落日始 9 点。

    2026-11-06 曾拍板「按正常景点排」，实际效果是随日始落到 09:00（无场次
    晨卡事故）；2026-11-11 用户改拍「无场次 SHOW 设成可以下午或者晚上」，
    下界抬到 12:00，上界仍按日终收口。
    """
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_visit("v_show", poi_id="p_all", dur=80, best_visit_time="show")],
    )
    # 无营业时间条目、无场次串 → 下午或晚上域，makespan 取最早可行 = 正午
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    start = _minutes(solved.items[0].start_time)
    assert start == 12 * 60
    assert _minutes(solved.items[0].end_time) == start + 80


def test_show_with_show_hours_starts_at_window_open():
    """带场演营业时间（19:00-21:30）时落在窗内最早可行位：19:00 开场 20:20 散场。"""
    hours = [PoiHours(poi_id="p_show", opens=time(19, 0), closes=time(21, 30))]
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_visit("v_show", poi_id="p_show", dur=80, best_visit_time="show")],
    )
    solved = solve_day(day, poi_hours=hours)
    assert solved is not None
    assert _minutes(solved.items[0].start_time) == 19 * 60
    assert _minutes(solved.items[0].end_time) == 20 * 60 + 20


def test_entertainment_category_without_sessions_schedules_normally():
    """库行 category=entertainment 无场次同样按正常景点逻辑（种子路径）。"""
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_visit("v_show", poi_id="p_show", dur=80, category="entertainment")],
    )
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    assert _minutes(solved.items[0].start_time) == 9 * 60


def test_show_and_daytime_visit_share_day_without_overlap():
    """经典耦合（兵马俑白天 + 长恨歌晚场）：同日共存互不挤压。"""
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit("v_day", poi_id="p_day", dur=150, best_visit_time="morning"),
            _visit("v_show", poi_id="p_show", dur=80, best_visit_time="show"),
        ],
    )
    hours = [
        PoiHours(poi_id="p_day", opens=time(8, 0), closes=time(18, 0)),
        PoiHours(poi_id="p_show", opens=time(19, 0), closes=time(21, 30)),
    ]
    solved = solve_day(day, poi_hours=hours)
    assert solved is not None
    show = next(i for i in solved.items if i.item_id == "v_show")
    dayt = next(i for i in solved.items if i.item_id == "v_day")
    assert _minutes(dayt.end_time) <= _minutes(show.start_time)
    assert _minutes(show.start_time) == 19 * 60  # 场演营业窗开门即排


# --- 2026-10-30 走行分离（travel-aware arcs）+ 不可行回落 ---------------------


def test_travel_gap_enforced_between_consecutive_visits():
    """矩阵给出走行分钟时，相邻两场之间必须留足走行时间（零走行衔接事故：
    上一场 09:30 散场、7.3km 外下一场 09:30 开场）。"""
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _visit("a", poi_id="pa", dur=60),
            _visit("b", poi_id="pb", dur=60),
        ],
    )
    matrix = {("pa", "pb"): 40, ("pb", "pa"): 40}

    solved = solve_day(day, poi_hours=[_ALL_DAY], travel_minutes=matrix)

    assert solved is not None
    first, second = solved.items
    gap = _minutes(second.start_time) - _minutes(first.end_time)
    assert gap >= 40


def test_infeasible_travel_separation_drops_day():
    """走行分离把当天挤爆（时段窗钉死 + 240 分钟走行）→ 弃日返回 None，
    交上层 _fallback_sequence_times 带腿重排/留空披露——不再回落 gap=0
    背靠背语义（2026-11-03 Day2 大明宫→城墙 15:00 零车程事故拍板：
    零间隔不合法化，宁可披露也不硬排）。"""
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _visit("m", poi_id="pm", dur=180, best_visit_time="morning"),
            _visit("e", poi_id="pe", dur=180, best_visit_time="afternoon"),
        ],
    )
    matrix = {("pm", "pe"): 240, ("pe", "pm"): 240}

    solved = solve_day(day, poi_hours=[_ALL_DAY], travel_minutes=matrix)

    assert solved is None


# --- 2026-10-31 白天入场闸（非演出观光点最晚 16:00 入场） ---------------------


def test_generic_sightseeing_entry_capped_at_16():
    """城墙·碑林案：下午被 pinned 180 分钟占满（13:30-16:30）时，景区
    不许 17:00 入场——只能排上午（solver 主路收编）。"""
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit(
                "blocker",
                poi_id="p_b",
                dur=180,
                category="attraction",
                pinned=True,
                start_time=time(13, 30),
            ),
            _visit("wall", poi_id="p_w", dur=180, category="attraction"),
        ],
    )

    solved = solve_day(day, poi_hours=[])

    assert solved is not None
    wall = next(i for i in solved.items if i.item_id == "wall")
    assert _minutes(wall.start_time) <= 16 * 60
    assert wall.end_time <= time(13, 30)  # 只能排上午（pin 前）


def test_food_dinner_uncapped_while_scenic_capped():
    """晚餐（food）照旧可排傍晚；同日景区被 16:30 开场闸收进上午。"""
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit(
                "blocker",
                poi_id="p_b",
                dur=330,
                category="attraction",
                pinned=True,
                start_time=time(11, 30),
            ),  # 11:30-17:00
            _visit("wall", poi_id="p_w", dur=150, category="attraction"),
            _visit("dinner", poi_id="p_f", dur=60, category="food"),
        ],
    )

    solved = solve_day(day, poi_hours=[])

    assert solved is not None
    wall = next(i for i in solved.items if i.item_id == "wall")
    dinner = next(i for i in solved.items if i.item_id == "dinner")
    # wall 150 分钟只能进上午（blocker 后 17:00 起排 > 16:30 开场闸）
    assert wall.end_time <= time(11, 30)
    assert _minutes(wall.start_time) <= 16 * 60
    # 晚餐不受闸：blocker 之后 17:00 开饭（闸后时段照排）
    assert dinner.start_time >= time(17, 0)


def test_late_open_venue_end_gate_boundary_not_placeable():
    """2026-11-05 终裁（武侯祠 15:23+90=16:53 判违规）：闸=结束闸，
    观光占用须 16:30 前收尾——晨满（09:00-16:30 固定件）后 75 分钟
    轻点唯一档 16:30-17:45 越闸 → 整日降级（「16:30 整点开场合法」的
    11-03 开场口径废除）；固定件收尾腾到 14:30 时，15:00-16:15 照常
    可排（同一闸内的对照锚）。"""
    hours = [PoiHours(poi_id="p_late", opens=time(8, 30), closes=time(22, 0))]
    day_blocked = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit(
                "blocker",
                poi_id="p_b",
                dur=450,
                pinned=True,
                start_time=time(9, 0),
            ),  # 09:00-16:30
            _visit("v_late", poi_id="p_late", dur=75, category="attraction"),
        ],
    )
    assert solve_day(day_blocked, poi_hours=hours) is None

    day_free = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit(
                "blocker",
                poi_id="p_b",
                dur=330,
                pinned=True,
                start_time=time(9, 0),
            ),  # 09:00-14:30
            _visit("v_late", poi_id="p_late", dur=75, category="attraction"),
        ],
    )
    solved = solve_day(day_free, poi_hours=hours)
    assert solved is not None
    v = next(i for i in solved.items if i.item_id == "v_late")
    # 固定件 14:30 收尾后紧接可排（CP 实选 14:30 背靠背），收尾必须在闸内
    assert v.start_time >= time(14, 30)
    assert v.end_time is not None and v.end_time <= time(16, 30)


def test_night_combo_pair_schedules_back_to_back():
    """夜档贴排组合（2026-11-07 拍板「不是各排各卡，而是两卡贴排，作为
    一个 SITE 排列组合」）：≤1.5km 的夜档点（bvt=show）与普通观光点绑成
    一个排程单元——普通点贴排在夜档点开场前收尾（大雁塔 13:00-16:00 →
    长安十二时辰 16:00 形态），夜档点守 16:00 后开场。"""
    hours = [_ALL_DAY]
    near = dict(
        dyt={
            "lon": 108.959,
            "lat": 34.218,
        },
        shier={"lon": 108.964, "lat": 34.221},  # ~0.55km，绑
    )
    for scheduler in ("insertion", "cp"):
        items = [
            _visit("dyt", poi_id="p_all", dur=180, location=near["dyt"]),
            _visit(
                "shier",
                poi_id="p_all",
                dur=240,
                location=near["shier"],
                best_visit_time="show",
            ),
        ]
        plan = ItineraryPlan(
            itinerary_id="it_night_combo",
            cities=["西安"],
            days=[DayPlan(day=1, base_city="西安", items=items)],
        )
        solved = solve_plan(plan, poi_hours=hours, scheduler=scheduler)
        assert solved is not None, scheduler
        dyt = next(i for i in solved.days[0].items if i.item_id == "dyt")
        shier = next(i for i in solved.days[0].items if i.item_id == "shier")
        assert _minutes(shier.start_time) >= 16 * 60, scheduler
        gap = _minutes(shier.start_time) - _minutes(dyt.end_time)
        assert 0 <= gap <= 30, scheduler  # 贴排：间隔仅走行分钟
        assert _minutes(dyt.start_time) >= 12 * 60, scheduler  # 下午档非晨头


def test_night_combo_far_pair_not_bound():
    """>1.5km 的夜档点不绑：两卡各排各卡（贴排只属贴邻组合）。"""
    hours = [_ALL_DAY]
    items = [
        _visit(
            "dyt_far",
            poi_id="p_all",
            dur=180,
            location={"lon": 109.009, "lat": 34.218},  # ~4.7km，不绑
        ),
        _visit(
            "shier",
            poi_id="p_all",
            dur=240,
            location={"lon": 108.964, "lat": 34.221},
            best_visit_time="show",
        ),
    ]
    plan = ItineraryPlan(
        itinerary_id="it_night_combo_far",
        cities=["西安"],
        days=[DayPlan(day=1, base_city="西安", items=items)],
    )
    solved = solve_plan(plan, poi_hours=hours, scheduler="insertion")
    assert solved is not None
    dyt = next(i for i in solved.days[0].items if i.item_id == "dyt_far")
    shier = next(i for i in solved.days[0].items if i.item_id == "shier")
    gap = _minutes(shier.start_time) - _minutes(dyt.end_time)
    assert _minutes(shier.start_time) < 16 * 60 or abs(gap) > 30
