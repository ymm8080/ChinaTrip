# -*- coding: utf-8 -*-
"""起始城市游玩天数（2026-11-22 用户拍板「起始城市也要能够选游玩日期数」）。

口径：origin_days ≥1 时出发城是真实首站——Day1..k 在出发城活动，
Day k+1 早上转场去第一目的地；闭合行程出发城=尾城，起始段占 (1,k)
选点窗、尾段日（返程腿日..days）由腿日表（_city_leg_start_days，
并集前口径）供转场/回填使用；k=0 保持「出发日只排交通」旧口径。
"""

from __future__ import annotations

from app.services.agent.plan import _city_day_ranges, _city_leg_start_days
from app.services.trip_orchestrator.session import PlanSession
from app.services.trip_solver.entry import seam_plain_shape


def test_origin_window_open_trip():
    # 北京(2)→成都(3)→重庆(3)，8 天：起始段 (1,2)，目的地右移切窗
    assert _city_day_ranges(["北京", "成都", "重庆"], 8, {"成都": 3, "重庆": 3}, 2) == {
        "成都": (3, 5),
        "重庆": (6, 8),
        "北京": (1, 2),
    }


def test_origin_window_closed_trip_origin_segment_wins_ranges():
    # 北京(2)→成都(3)→重庆(3)→北京(尾2)，10 天：出发城=尾城同名键只有
    # 一份——选点窗给起始段 (1,2)，尾段日走腿日表（不许读本表）。
    assert _city_day_ranges(
        ["北京", "成都", "重庆", "北京"], 10, {"成都": 3, "重庆": 3, "北京": 2}, 2
    ) == {
        "成都": (3, 5),
        "重庆": (6, 8),
        "北京": (1, 2),
    }


def test_leg_days_closed_trip_with_origin_stay():
    # 去程腿=起始段末日+1（day3）、hop=目的地窗首日（day6）、
    # 返程腿=尾段窗口首日（day9）——绝不能错排到 day1。
    assert _city_leg_start_days(
        ["北京", "成都", "重庆", "北京"], 10, {"成都": 3, "重庆": 3, "北京": 2}, 2
    ) == [3, 6, 9]


def test_leg_days_without_origin_stay_unchanged():
    # k=0 旧口径：去程 day1、hop 逐城+1、闭合返程=尾城窗首日（本例=7）
    assert _city_leg_start_days(
        ["北京", "成都", "重庆", "北京"], 8, {"成都": 3, "重庆": 3, "北京": 2}, 0
    ) == [1, 4, 7]
    # 3 天闭合无 city_days：1,2,3（2026-10-30 锚原样）
    assert _city_leg_start_days(["上海", "西安", "重庆", "上海"], 3, {}, 0) == [1, 2, 3]


def test_origin_days_clamped_when_exceeds_trip():
    # 起始天数=总天数：钳到 days-1，目的地至少留 1 天
    assert _city_day_ranges(["北京", "成都"], 3, {"成都": 1}, 3) == {
        "成都": (3, 3),
        "北京": (1, 2),
    }


def test_seam_gate_rejects_origin_stay():
    # 引擎 C-17 出发城不占活动窗——起始城停留形状留 legacy
    assert seam_plain_shape(days=8, cities=["北京", "成都"], origin_days=2) is False
    assert seam_plain_shape(days=8, cities=["北京", "成都"]) is True


def test_session_defaults_origin_days_zero():
    # 会话缺省 0=旧口径；字段随快照持久化（payload round-trip 同名）
    s = PlanSession(session_id="t", device_id="d")
    assert s.origin_days == 0
    s2 = PlanSession.model_validate(s.model_dump())
    assert s2.origin_days == 0


def test_evict_past_midnight_sights():
    # 2026-11-22 起始城停留案：补点/顺延链把光标推过 1440，_time_of 钳成
    # 23:59 假条目（北京中轴线 23:59-23:59 实录）→ 终扫移出转想排。
    from datetime import date, time

    from app.services.agent.plan import _evict_past_midnight_sights
    from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem

    def _v(item_id, name, start, end, cat="historic"):
        return VisitItem(
            item_id=item_id,
            name=name,
            city="北京",
            day=2,
            category=cat,
            duration_minutes=90,
            start_time=start,
            end_time=end,
        )

    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["北京"],
        days=[
            DayPlan(
                day=2,
                base_city="北京",
                date=date(2026, 11, 26),
                items=[
                    _v("a", "北京中轴线", time(23, 59), time(23, 59)),
                    _v("b", "夜游商场", time(21, 0), time(22, 30), "citywalk"),
                    _v("c", "零长卡", time(20, 0), time(20, 0)),
                    _v("d", "晚饭", time(19, 0), time(20, 30), "food"),
                ],
            )
        ],
    )
    notes = _evict_past_midnight_sights(plan)
    names = [i.name for i in plan.days[0].items]
    assert "北京中轴线" not in names and "零长卡" not in names
    assert "夜游商场" in names and "晚饭" in names  # 正常夜间件/餐卡不动
    assert [u.reason for u in plan.unplaced] == ["day_overflow", "day_overflow"]
    assert len(notes) == 2
    # 幂等
    assert _evict_past_midnight_sights(plan) == []
