# -*- coding: utf-8 -*-
"""2026-11-13 陕历博灰卡案：季节作息解析回归锚。

事实：POI opening_hours=「4月1日至11月14日 08:30-19:00…；11月15日至3月14日
周二至周日 09:00-17:30」——旧解析把内段当午休，补集成 08:30-09:00 +
17:30-19:00 两片碎窗，240min 必去件任何一天都探不进 → None-None 灰卡。
"""

from __future__ import annotations

from datetime import time as T

from app.services.agent.plan import _hours_from_visit, _must_visit_room_sweep
from app.services.itinerary.models import DayPlan, ItineraryPlan, PoiHours, VisitItem

MUSEUM_HOURS = (
    "4月1日至11月14日 08:30-19:00 (18:00停止检票),"
    "11月15日至3月14日周一 全天关闭(法定节假日除外), "
    "周二至周日09:00-17:30 (16:30停止检票)"
)


def _hours(pid, text):
    return _hours_from_visit(
        VisitItem(
            item_id="v", name="x", city="西安", day=1, poi_id=pid, opening_hours=text
        )
    )


def test_seasonal_hours_take_inner_window():
    """两套作息 → 取交集（内段），不再拆成碎窗。"""
    h = _hours("m1_x", MUSEUM_HOURS)
    assert isinstance(h, PoiHours)
    assert h.windows is None
    assert (h.opens, h.closes) == (T(9, 0), T(17, 30))


def test_midday_break_still_complement():
    """G3 午休型口径不变：09:00-17:00（12:00-13:30 午休）仍是两段。"""
    h = _hours("p1", "09:00-17:00（12:00-13:30 午休）")
    assert h.windows == [(T(9, 0), T(12, 0)), (T(13, 30), T(17, 0))]


def test_duplicate_window_collapses():
    """同一窗重复两遍（周一闭馆 + 节假日照常）不得塌成零长窗。"""
    h = _hours(
        "p2", "周二至周日 09:00-17:00 最晚进入16:30；节假日 09:00-17:00 最晚进入16:30"
    )
    assert h.windows is None
    assert (h.opens, h.closes) == (T(9, 0), T(17, 0))


def _visit(iid, name, cat, pid, dur, start=None, end=None, **kw):
    return VisitItem(
        item_id=iid,
        name=name,
        poi_id=pid,
        category=cat,
        city="西安",
        day=3,
        duration_minutes=dur,
        start_time=start,
        end_time=end,
        **kw,
    )


def test_must_visit_gets_room_after_hours_fix():
    """必去 240min 博物馆 × 同日 180min 景点：让位闸必须给它腾出整档。"""
    museum = _visit(
        "v-museum",
        "陕西历史博物馆",
        "museum",
        "m1_f1fd2d8d516e",
        240,
        pinned=True,
        must=True,
        opening_hours=MUSEUM_HOURS,
    )
    day = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit(
                "v-wall",
                "城墙·碑林历史文化景区",
                "attraction",
                "5a_304",
                180,
                T(12, 43),
                T(15, 43),
            ),
            _visit(
                "v-lunch", "午饭", "food", "f1", 30, T(12, 0), T(12, 30), soft_pin=True
            ),
            museum,
        ],
    )
    plan = ItineraryPlan(itinerary_id="it-h", cities=["西安"], days=[day])
    notes = _must_visit_room_sweep(plan)

    assert notes, "必去让位闸必须给出留痕披露"
    assert any("城墙" in n for n in notes)
    assert any(u.name == "城墙·碑林历史文化景区" for u in plan.unplaced)
    assert museum in day.items
