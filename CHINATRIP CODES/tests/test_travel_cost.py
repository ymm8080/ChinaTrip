# -*- coding: utf-8 -*-
"""_travel_cost 对段卡防御（2026-11-17）：跨城日交通卡不再崩插入式排程。

历史「solver raised, degrading」7 次的元凶：TransferItem 无 poi_id，
_travel_cost 直接 a.poi_id 抛 AttributeError → _solve 捕获 → 整程降级。
"""

from datetime import time

from app.services.itinerary.models import DayPlan, TransferItem, VisitItem
from app.services.itinerary.solver import (
    DEFAULT_TRAVEL_MINUTES,
    _travel_cost,
    insertion_schedule_day,
)


def _visit(iid, name, dur=60):
    return VisitItem(item_id=iid, name=name, city="西安", day=1, duration_minutes=dur)


def _transfer(iid="t1"):
    return TransferItem(
        item_id=iid,
        day=1,
        seq=1,
        from_city="西安",
        to_city="成都",
        mode="train",
        start_time=time(9, 0),
        end_time=time(12, 30),
    )


def test_travel_cost_tolerates_transfer_item():
    t, v = _transfer(), _visit("v1", "碑林")
    # 段卡无 poi_id：不得抛 AttributeError，走 item_id/默认代价
    assert _travel_cost(t, v, {}) == DEFAULT_TRAVEL_MINUTES
    assert _travel_cost(v, t, {}) == DEFAULT_TRAVEL_MINUTES
    # poi_id 矩阵命中仍正常
    v.poi_id = "p1"
    v2 = _visit("v2", "城墙")
    v2.poi_id = "p2"
    assert _travel_cost(v, v2, {("p1", "p2"): 12}) == 12


def test_insertion_with_transfer_card_does_not_raise():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_visit("v1", "碑林", 90), _transfer(), _visit("v2", "城墙", 90)],
    )
    # 不崩即达标（结果为 None 或解都允许——防御的是 AttributeError）
    insertion_schedule_day(day, poi_hours=[])
