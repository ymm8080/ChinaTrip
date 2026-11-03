# -*- coding: utf-8 -*-
"""2026-11-03 拍板「演出优先傍晚/晚场」回归（Day4 秦俑情 11:00 早场
事故形态：演出霸晨 → 「上午一个点」把大雁塔/半坡全罚到午后）：

1. 插入路：多场次演出（11:00/14:00/17:00）落 17:00 晚场，观光点进上午。
2. CP 路（solve_day）：同上；makespan 让位于早场罚。
3. 兜底路（_fallback_sequence_times）：场次偏好序=晚场升序在前，
   早场升序兜底——不再升序首中霸晨。
4. 纯早场演出照排（软偏好不拦可行性）。
5. 用户钉住场次不动（铁律 19），评分器不罚钉场。
6. 评分器 early_show 软罚与 solver 早场罚同向（LNS 不回挪早场）。
"""

from datetime import time

from app.services.agent.plan import _fallback_sequence_times
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.scoring import plan_score
from app.services.itinerary.solver import insertion_schedule_day, solve_day


def _visit(item_id, *, dur=60, day=1, city="西安", **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city=city,
        day=day,
        duration_minutes=dur,
        **kw,
    )


def _show(item_id="qyq", hours="多场（约11:00/14:00/17:00，以当日公告为准）"):
    return _visit(
        item_id,
        dur=80,
        best_visit_time="show",
        category="entertainment",
        opening_hours=hours,
    )


def _sight(item_id="sight", dur=120):
    return _visit(item_id, dur=dur)


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


def _starts(day):
    return {i.item_id: i.start_time for i in day.items if i.start_time is not None}


# ---------- 1) 插入路 ----------


def test_insertion_prefers_late_session():
    show, sight = _show(), _sight()
    day = DayPlan(day=1, base_city="西安", items=[show, sight, _lunch()])

    solved = insertion_schedule_day(day, poi_hours=[])

    assert solved is not None
    starts = _starts(solved)
    assert starts["qyq"] == time(17, 0)  # 晚场优先，不占上午
    assert starts["sight"] == time(9, 0)  # 上午名额留给观光点


def test_insertion_early_only_sessions_still_schedule():
    show, sight = _show(hours="多场（白天约10:30/13:30）"), _sight()
    day = DayPlan(day=1, base_city="西安", items=[show, sight, _lunch()])

    solved = insertion_schedule_day(day, poi_hours=[])

    assert solved is not None
    starts = _starts(solved)
    assert starts["qyq"] in (time(10, 30), time(13, 30))  # 软偏好不拦可行性


def test_insertion_pinned_session_untouched():
    show = _show()
    show.pinned = True
    show.start_time = time(11, 0)
    show.end_time = time(12, 20)
    day = DayPlan(day=1, base_city="西安", items=[show, _lunch()])

    solved = insertion_schedule_day(day, poi_hours=[])

    assert solved is not None
    assert _starts(solved)["qyq"] == time(11, 0)  # 铁律 19：钉场不迁移


# ---------- 2) CP 路 ----------


def test_cp_prefers_late_session():
    show, sight = _show(), _sight()
    day = DayPlan(day=1, base_city="西安", items=[show, sight, _lunch()])

    solved = solve_day(day, poi_hours=[])

    assert solved is not None
    # makespan 让位于早场罚（17:00 晚场 vs 14:00 早收工）——sight 时刻
    # 在 makespan 平手下不保证，不在此断言。
    assert _starts(solved)["qyq"] == time(17, 0)


# ---------- 3) 兜底路 ----------


def test_fallback_prefers_late_session():
    show, sight = _show(), _sight(dur=90)
    day = DayPlan(day=1, base_city="西安", items=[sight, show, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    _fallback_sequence_times(plan)

    starts = _starts(day)
    assert starts["qyq"] == time(17, 0)
    assert starts["sight"] == time(9, 0)


def test_fallback_late_session_infeasible_falls_to_early():
    """晚场被离城腿夹死（17:30 发车：17:00 场散场 18:20 城市侧已
    不可行）→ 偏好序回落早场照排，不留空。11:00 场撞钉死午餐，
    14:00 场（15:20 散场，留足 90 分钟铁律 4 缓冲）为唯一可行。
    用汽车腿夹晚场：火车/大巴/飞机会触发离城日上午闸（2026-11-03
    拍板，≥12:00 发车出发城条目一律上午收尾）——14:00 场同样不可行，
    本用例只测「晚场不可行回落早场」的偏好序本身。"""
    from app.services.itinerary.models import TransferItem

    show = _show()
    leg = TransferItem(
        day=1,
        seq=1,
        mode="car",
        item_id="t1",
        from_city="西安",
        to_city="上海",
        start_time=time(17, 30),
        end_time=time(20, 30),
        duration_minutes=180,
    )
    day = DayPlan(day=1, base_city="西安", items=[show, leg, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    _fallback_sequence_times(plan)

    assert _starts(day)["qyq"] == time(14, 0)


# ---------- 4) 评分器 ----------


def _scored_show_plan(pinned: bool) -> VisitItem:
    show = _show()
    show.start_time = time(14, 0)
    show.end_time = time(15, 20)
    show.pinned = pinned
    return show


def test_scorer_penalizes_early_show():
    show = _scored_show_plan(pinned=False)
    day = DayPlan(day=1, base_city="西安", items=[show, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    sc = plan_score(plan)

    assert sc.soft["early_show"] == -12
    assert sc.counts["early_show"] == 1


def test_scorer_late_show_zero_penalty():
    show = _show()
    show.start_time = time(17, 0)
    show.end_time = time(18, 20)
    day = DayPlan(day=1, base_city="西安", items=[show, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    sc = plan_score(plan)

    assert sc.soft["early_show"] == 0


def test_scorer_pinned_early_show_exempt():
    show = _scored_show_plan(pinned=True)
    day = DayPlan(day=1, base_city="西安", items=[show, _lunch()])
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])

    sc = plan_score(plan)

    assert sc.soft["early_show"] == 0  # 铁律 19：用户钉场不罚
