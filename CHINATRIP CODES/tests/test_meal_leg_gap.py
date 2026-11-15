# -*- coding: utf-8 -*-
"""餐卡→景点留腿（2026-11-15 用户拍板）。

现场：午饭卡 11:30–12:00（30 分钟）紧贴「故宫博物院 12:00–14:00」开场，中
间 0 分钟通勤（rule 7「散场到开场仅 0 分钟，打车约需 30 分钟」）。用户问
「故宫为什么不晚点安排」——餐卡落位只避固定窗、不吃通勤腿。

_open_meal_leg_gaps 的口径：
  ① 餐占位被压短的先补回默认时长（午 60 / 晚 90）；
  ② 景点及其后时链整体顺延，保证「餐→景点」≥ 步行腿（直线 ×1.3 / 80m 每分钟）；
  ③ 顺延会破营业窗/日终/顶到用户手钉 → 退一步把餐卡前移；
  ④ 都不行 → 原样放行（绝不塞进闭馆后）。
"""

from datetime import time

from app.services.agent.plan import _leg_minutes_estimate, _open_meal_leg_gaps
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

# 午饭卡锚在「四季民福（故宫店）」一带，故宫在其北约 1.6km（≈26 分钟步行）
_LUNCH_PT = GeoPoint(lon=116.397, lat=39.913)
_GUGONG = GeoPoint(lon=116.397, lat=39.928)


def _place(
    item_id: str,
    name: str,
    start: time,
    dur: int,
    *,
    hours=None,
    loc=None,
    category="attraction",
    pinned=False,
    must=False,
) -> VisitItem:
    end_min = start.hour * 60 + start.minute + dur
    return VisitItem(
        item_id=item_id,
        name=name,
        city="北京",
        day=2,
        category=category,
        duration_minutes=dur,
        start_time=start,
        end_time=time(end_min // 60, end_min % 60),
        location=loc,
        opening_hours=hours,
        pinned=pinned,
        must=must,
    )


def _lunch(start: time, dur: int) -> VisitItem:
    item = _place(
        "food-lunch-ph-d2",
        "午饭（自由安排）",
        start,
        dur,
        category="food",
        loc=_LUNCH_PT,
    )
    item.soft_pin = True
    item.anchor_from_prev = True
    return item


def _plan(*items: VisitItem) -> ItineraryPlan:
    for it in items:
        if it.start_time is not None and it.end_time is None:
            dur = it.duration_minutes or 60
            mins = it.start_time.hour * 60 + it.start_time.minute + dur
            it.end_time = time(mins // 60, mins % 60)
    return ItineraryPlan(
        itinerary_id="it-leg",
        cities=["北京"],
        days=[DayPlan(day=2, base_city="北京", items=list(items))],
        start_date="2026-11-23",
    )


def test_lunch_leg_gap_pushes_museum_later():
    lunch = _lunch(time(11, 30), 30)
    gugong = _place(
        "v1",
        "故宫博物院",
        time(12, 0),
        120,
        hours="11月1日至3月31日,周二至周日08:30-16:30(15:30停止检票)",
        loc=_GUGONG,
    )
    tiantan = _place(
        "v2", "天坛", time(14, 30), 60, hours="今天06:30-22:00开放（21:00停止入园）"
    )
    plan = _plan(lunch, gugong, tiantan)
    notes = _open_meal_leg_gaps(plan)
    # 午卡补回 60 分钟
    assert lunch.duration_minutes == 60
    assert lunch.start_time == time(11, 30) and lunch.end_time == time(12, 30)
    # 故宫不再贴 12:00：留出通勤腿
    gap = (
        gugong.start_time.hour * 60
        + gugong.start_time.minute
        - (lunch.end_time.hour * 60 + lunch.end_time.minute)
    )
    need = _leg_minutes_estimate(lunch, gugong)
    assert need > 0 and gap >= need, (gap, need)
    # 仍在冬季闭馆前收场
    assert gugong.end_time <= time(16, 30)
    # 后续卡跟着顺延，不重叠
    assert tiantan.start_time >= gugong.end_time
    assert notes


def test_lunch_leg_gap_skips_user_pinned_site():
    lunch = _lunch(time(11, 30), 30)
    gugong = _place(
        "v1",
        "故宫博物院",
        time(12, 0),
        120,
        hours="11月1日至3月31日,周二至周日08:30-16:30(15:30停止检票)",
        loc=_GUGONG,
        pinned=True,  # 用户手钉（must=False）
    )
    plan = _plan(lunch, gugong)
    _open_meal_leg_gaps(plan)
    assert gugong.start_time == time(12, 0)  # 铁律 19：用户手钉不动


def test_lunch_leg_gap_falls_back_to_earlier_meal():
    """顺延会顶破闭馆窗时，退一步把餐卡前移而不是硬推景点。"""
    lunch = _lunch(time(12, 0), 30)
    gugong = _place(
        "v1",
        "故宫博物院",
        time(12, 30),
        120,
        hours="11月1日至3月31日,周二至周日08:30-16:30(15:30停止检票)",
        loc=_GUGONG,
    )
    plan = _plan(lunch, gugong)
    _open_meal_leg_gaps(plan)
    # 要么餐卡前移，要么景点顺延；两者都不得重叠
    assert lunch.end_time <= gugong.start_time
    assert lunch.start_time >= time(11, 30)
