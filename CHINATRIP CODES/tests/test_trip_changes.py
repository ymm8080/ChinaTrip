# -*- coding: utf-8 -*-
"""行程变更日志（2026-11-13 用户拍板）——diff/摘要纯函数锚。"""

from __future__ import annotations

from datetime import time

from app.services.itinerary import VisitItem
from app.services.itinerary.models import DayPlan, ItineraryPlan
from app.services.trip_changes import diff_plans, summarize


def _item(name, day, start):
    return VisitItem(
        item_id=f"v-{name}-{day}",
        name=name,
        city="西安",
        day=day,
        start_time=time.fromisoformat(start),
        category="attraction",
        poi_id=f"poi-{name}",
    )


def _plan(*days):
    return ItineraryPlan(
        itinerary_id="it-test",
        cities=["西安"],
        days=[DayPlan(day=d, base_city="西安", items=items) for d, items in days],
    )


def test_diff_add_remove_move_retime():
    old = _plan(
        (1, [_item("大雁塔", 1, "09:00"), _item("城墙", 1, "14:00")]),
        (2, [_item("兵马俑", 2, "09:00")]),
    )
    new = _plan(
        (
            1,
            [
                _item("大雁塔", 1, "10:00"),
                _item("钟楼", 1, "14:00"),
                _item("兵马俑", 1, "13:00"),
            ],
        ),
        (2, []),
    )
    ops = sorted(c["op"] for c in diff_plans(old, new))
    assert ops == ["add", "move", "remove", "retime"]


def test_summary_is_human_readable():
    old = _plan((1, [_item("大雁塔", 1, "09:00")]))
    new = _plan((1, [_item("大雁塔", 1, "10:00")]))
    text = summarize(diff_plans(old, new))
    assert "改时" in text and "大雁塔" in text


def test_no_change_summary():
    plan = _plan((1, [_item("大雁塔", 1, "09:00")]))
    assert summarize(diff_plans(plan, plan)) == "保存（无行程内容变化）"
