# -*- coding: utf-8 -*-
"""闭合行程（同城往返，上海→西安→上海）簇不拆天/王牌不落返程日锚
（2026-11-08 沪→西→沪案）。

用户案：D2-D4 被转场日压缩后——大雁塔↔十二时辰、城墙·碑林↔碑林博
拆天；兵马俑（tier1 王牌）被 first-fit 挪日塞进 D5 返程日上午（17:00
返沪航班前）。三锚：
① _day_has_departure 认离城腿（到达腿不算）；
② _host_day_for_visit 返程日殿后——有非返程宿主绝不首选返程日；
③ 返程日仍可作最后归宿（轻量件合法，离城上午闸口径不破）。
"""

from datetime import time

from app.services.agent.plan import _day_has_departure, _host_day_for_visit
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    TransferItem,
    VisitItem,
)

_BL = GeoPoint(lon=108.9397, lat=34.2565)  # 碑林（城心簇）


def _visit(name: str, dur: int, loc: GeoPoint | None, day: int = 1) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="西安",
        day=day,
        duration_minutes=dur,
        location=loc,
    )


def _return_day(day_no: int = 5) -> DayPlan:
    """D5 返程日：17:00 西安→上海 航班。"""
    return DayPlan(
        day=day_no,
        base_city="西安",
        items=[
            TransferItem(
                item_id="t-ret",
                day=day_no,
                seq=1,
                from_city="西安",
                to_city="上海",
                mode="flight",
                start_time=time(17, 0),
                end_time=time(19, 30),
            )
        ],
    )


def test_day_has_departure_recognizes_leaving_leg_only():
    dep = _return_day()
    arr = DayPlan(
        day=1,
        base_city="上海",
        items=[
            TransferItem(
                item_id="t-arr",
                day=1,
                seq=1,
                from_city="上海",
                to_city="西安",
                mode="flight",
                start_time=time(9, 0),
                end_time=time(12, 0),
            )
        ],
    )
    plain = DayPlan(day=2, base_city="西安", items=[])
    assert _day_has_departure(dep, "西安") is True
    assert _day_has_departure(dep, "上海") is False  # 只认自该城离城
    assert _day_has_departure(arr, "西安") is False  # 到达腿不是返程日信号
    assert _day_has_departure(plain, "西安") is False


def test_host_day_prefers_non_departure_day_for_big_visit():
    """兵马俑 D5 案锚：返程日排探查序末位——空荡的 D5 不得抢在可用的
    非返程日前收 180min 大点。"""
    d4 = DayPlan(day=4, base_city="西安", items=[_visit("骊山", 120, _BL, day=4)])
    d5 = _return_day()
    host = _host_day_for_visit(
        [d5, d4], "西安", 180, incoming=_BL, visit=_visit("兵马俑", 180, _BL)
    )
    assert host is d4


def test_host_day_departure_day_usable_as_last_resort():
    """返程日不硬拦：无非返程宿主时轻量件仍可落（离城上午闸合法件）。"""
    d5 = _return_day()
    host = _host_day_for_visit(
        [d5], "西安", 60, incoming=_BL, visit=_visit("永兴坊", 60, _BL)
    )
    assert host is d5
